"""Offline whole-segment GDAL mosaic. Research preview, never for navigation.

Uses GDALBuildVRT/GDALWarp (the gdalbuildvrt/gdalwarp utility APIs), including
rasterio's bundled GDAL when the command-line programs are not installed.
See README.md for the explicit source/vertical-offset contract.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes as ct
import ctypes.util
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

import numpy as np
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.warp import transform_bounds

NODATA = -999999.0
BAND_LIMIT_M = 300 * 0.3048
LABEL = 'NOT FOR NAVIGATION — research preview; review required'
# Seam feather (MB-02): the same 40 m elevation feather as scripts/build_bathy_tiles.py FEATHER_M, applied at
# every boundary between two contributors (tile edges of one survey family as well as between families).
FEATHER_M = 40.0
SEAM_SIGMA_CELLS = 8.0       # along-boundary smoothing of the offset estimate (80 m: offsets between surveys vary slowly)


def file_hash(path):
    with Path(path).open('rb') as stream:
        digest = sha256()
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class GDAL:
    """Small typed binding to the stable public GDAL utility C APIs."""

    def __init__(self):
        bundled = Path(rasterio.__file__).parent.parent / 'rasterio.libs'
        libraries = sorted(bundled.glob('*gdal*'))
        library = str(libraries[0]) if libraries else ctypes.util.find_library('gdal')
        if not library:
            raise RuntimeError('GDAL shared library not found; install the survey stack')
        self.lib = ct.CDLL(library)
        self._bind('GDALAllRegister', [], None)()
        self._bind('GDALOpen', [ct.c_char_p, ct.c_int], ct.c_void_p)
        self._bind('GDALClose', [ct.c_void_p], ct.c_int)
        self._bind('CPLGetLastErrorMsg', [], ct.c_char_p)
        ptrs = ct.POINTER(ct.c_void_p)
        strings = ct.POINTER(ct.c_char_p)
        for kind in ('BuildVRT', 'Warp'):
            self._bind(f'GDAL{"WarpApp" if kind == "Warp" else kind}OptionsNew', [strings, ct.c_void_p], ct.c_void_p)
            self._bind(f'GDAL{"WarpApp" if kind == "Warp" else kind}OptionsFree', [ct.c_void_p], None)
        self._bind('GDALBuildVRT', [ct.c_char_p, ct.c_int, ptrs, strings,
                                  ct.c_void_p, ct.POINTER(ct.c_int)], ct.c_void_p)
        self._bind('GDALWarp', [ct.c_char_p, ct.c_void_p, ct.c_int, ptrs,
                              ct.c_void_p, ct.POINTER(ct.c_int)], ct.c_void_p)

    def _bind(self, name, args, result):
        fn = getattr(self.lib, name)
        fn.argtypes, fn.restype = args, result
        return fn

    def run(self, kind, destination, sources, options):
        args = (ct.c_char_p * (len(options) + 1))(
            *[str(x).encode() for x in options], None)
        opts = getattr(self.lib, f'GDAL{"WarpApp" if kind == "Warp" else kind}OptionsNew')(args, None)
        if not opts:
            raise RuntimeError(f'GDAL {kind} rejected options')
        handles = []
        result = None
        try:
            for source in sources:
                handle = self.lib.GDALOpen(str(source).encode(), 0)
                if not handle:
                    raise RuntimeError(f'GDAL cannot open {source}')
                handles.append(handle)
            array = (ct.c_void_p * len(handles))(*handles)
            usage = ct.c_int()
            if kind == 'BuildVRT':
                result = self.lib.GDALBuildVRT(str(destination).encode(), len(handles),
                                              array, None, opts, ct.byref(usage))
            else:
                result = self.lib.GDALWarp(str(destination).encode(), None, len(handles),
                                          array, opts, ct.byref(usage))
            if not result or usage.value:
                raise RuntimeError(self.lib.CPLGetLastErrorMsg().decode())
        finally:
            if result:
                self.lib.GDALClose(result)
            for handle in handles:
                self.lib.GDALClose(handle)
            getattr(self.lib, f'GDAL{"WarpApp" if kind == "Warp" else kind}OptionsFree')(opts)


def json_write(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')


def local_file(value, base):
    # Never accept a URI, VSI address, or a user-supplied VRT with remote references.
    if not isinstance(value, str) or '://' in value or value.startswith('/vsi'):
        raise ValueError('Only local regular source files are accepted')
    path = (base / Path(value).expanduser()).resolve()
    if not path.is_file() or path.suffix.lower() not in {'.tif', '.tiff', '.bag'}:
        raise ValueError(f'Expected a cached TIFF or regular BAG: {path}')
    return path


def load_sources(path):
    path = Path(path).resolve()
    document = json.loads(path.read_text())
    if document.get('schema_version') != 1 or not document.get('sources'):
        raise ValueError('Expected schema_version=1 and nonempty sources')
    rows, ids = [], set()
    for row in document['sources']:
        row = dict(row)
        ident = row.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', ident) or ident in ids:
            raise ValueError('Source ids must be unique safe names')
        ids.add(ident)
        source = local_file(row['path'], path.parent)
        expected = row.get('sha256', '')
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Every source needs an exact lowercase SHA256 pin')
        actual = file_hash(source)
        if actual != expected:
            raise ValueError(f'Source hash changed: {ident}')
        resolution = row['resolution_m']
        offset = row['vertical_offset_m']
        if (isinstance(resolution, bool) or not isinstance(resolution, (float, int))
                or not math.isfinite(resolution) or resolution <= 0
                or isinstance(offset, bool) or not isinstance(offset, (float, int))
                or not math.isfinite(offset)):
            raise ValueError('Resolution and offset must be finite; resolution > 0')
        if row['value_convention'] not in {'elevation_positive_up', 'depth_positive_down'}:
            raise ValueError('An explicit source value_convention is required')
        if row['units'] != 'm':
            raise ValueError('Only explicit metre units supported')
        datum = row['vertical_datum']
        if datum not in {'MLLW', 'NAVD88', 'MSL', 'EGM2008', 'unstated', 'instantaneous_sea_level'}:
            raise ValueError('Unsupported vertical datum')
        if datum == 'unstated' and offset != 0:
            raise ValueError('Unstated datum must use zero offset and remain flagged')
        for field in ('citation', 'rights', 'attribution', 'offset_note'):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f'Explicit {field} is required')
        with rasterio.open(source) as grid:
            if grid.driver not in {'GTiff', 'BAG'} or grid.crs is None or grid.count < 1:
                raise ValueError('Expected georeferenced TIFF or BAG')
            if grid.driver == 'BAG':
                import h5py
                with h5py.File(source) as bag:
                    vr = bag.get('BAG_root/varres_refinements')
                    if vr is not None and vr.size:
                        raise ValueError('VR BAG overview refused; use an admitted regular composite')
            if not grid.crs.is_projected:
                raise ValueError('This MVP requires projected metre source grids')
            if grid.crs.linear_units != 'metre':
                raise ValueError('Source horizontal units must be metres')
            if not np.allclose(grid.res, [resolution, resolution], rtol=0.01, atol=0.01):
                raise ValueError(f'Declared resolution differs from native grid: {ident}')
            if grid.scales[0] != 1 or grid.offsets[0] != 0:
                raise ValueError('Nontrivial stored band scale/offset requires explicit normalization')
            row['source_crs'] = grid.crs.to_string()
            row['native_resolution_m'] = list(grid.res)
        row.update(path=str(source), bytes=source.stat().st_size,
                   datum_unresolved=datum == 'unstated',
                   vertical_transform_status='explicit_constant_only_not_a_geodetic_transform')
        rows.append(row)
    # Finest first, deterministic lexical tie break. Contributor codes follow this order.
    rows.sort(key=lambda row: (row['resolution_m'], row['id']))
    if len(rows) > 65534:
        raise ValueError('Too many sources for uint16 contributor/support rasters')
    for code, row in enumerate(rows, 1):
        row['code'] = code
    return rows


def normalized_vrt(source, output):
    """Normalize sign and apply explicit elevation offset, preserving masks/nodata."""
    with rasterio.open(source['path']) as grid:
        root = ET.Element('VRTDataset', rasterXSize=str(grid.width), rasterYSize=str(grid.height))
        ET.SubElement(root, 'SRS').text = grid.crs.to_wkt()
        ET.SubElement(root, 'GeoTransform').text = ','.join(map(str, grid.transform.to_gdal()))
        band = ET.SubElement(root, 'VRTRasterBand', dataType='Float32', band='1')
        ET.SubElement(band, 'NoDataValue').text = str(NODATA)
        node = ET.SubElement(band, 'ComplexSource')
        ET.SubElement(node, 'SourceFilename', relativeToVRT='0').text = source['path']
        ET.SubElement(node, 'SourceBand').text = '1'
        for tag in ('SrcRect', 'DstRect'):
            ET.SubElement(node, tag, xOff='0', yOff='0', xSize=str(grid.width), ySize=str(grid.height))
        if grid.nodata is not None:
            ET.SubElement(node, 'NODATA').text = str(grid.nodata)
        ET.SubElement(node, 'UseMaskBand').text = 'true'
        ET.SubElement(node, 'ScaleRatio').text = (
            '-1' if source['value_convention'] == 'depth_positive_down' else '1')
        ET.SubElement(node, 'ScaleOffset').text = str(source['vertical_offset_m'])
        ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)


def _shift(array, axis, step, fill):
    """array moved by `step` cells along `axis` (out[i] = array[i + step]); vacated cells get `fill`."""
    out = np.full_like(array, fill)
    src = [slice(None)] * array.ndim
    dst = [slice(None)] * array.ndim
    n = array.shape[axis]
    if step > 0:
        src[axis], dst[axis] = slice(step, n), slice(0, n - step)
    else:
        src[axis], dst[axis] = slice(0, n + step), slice(-step, n)
    out[tuple(dst)] = array[tuple(src)]
    return out


def seam_feather(elevation, codes, *, cell_m=10, feather_m=FEATHER_M, sigma_cells=SEAM_SIGMA_CELLS, pairs=None,
                 count=None):
    """Blend elevations across every contributor boundary; cells with no survey are never filled.

    At each 4-neighbour edge between two different valid contributors the vertical offset is the step
    across the edge minus the step the local slope explains (one-sided slopes from the next cell on
    each side, where that cell has the same contributor). The offset is smoothed along that pair's
    boundary (gaussian, `sigma_cells`). One smoothstep S across the 2 x `feather_m` band, centred on the
    boundary, then spreads it: each side moves by about half the offset at the boundary and by nothing
    at `feather_m`, so a cell whose centre is farther than `feather_m` from a boundary keeps its value
    exactly. Two abutting tiles need no overlap. This is a display blend, not a vertical-datum
    reconciliation; the contributor raster keeps the winning source of every cell.

    `pairs` (optional dict) accumulates per-boundary edge counts and offsets for edges whose first cell
    is inside `count` (a boolean mask of the cells this call owns, default: all).
    Returns (blended float32 elevation, changed-cell mask).
    """
    from scipy import ndimage
    elevation = np.asarray(elevation, dtype=np.float32)
    codes = np.asarray(codes)
    if feather_m <= cell_m / 2 or cell_m <= 0:
        raise ValueError('feather width must exceed half a cell and cell size must be positive')
    z = elevation.astype(np.float64)
    flat = np.arange(z.size).reshape(z.shape)
    sides = []                     # (own code, other code, flat cell index, half offset toward the other side)
    for axis in (0, 1):
        b, cb = _shift(z, axis, 1, np.nan), _shift(codes, axis, 1, 0)
        edge = (codes > 0) & (cb > 0) & (cb != codes)
        if not edge.any():
            continue
        a2, ca2 = _shift(z, axis, -1, np.nan), _shift(codes, axis, -1, 0)
        b2, cb2 = _shift(z, axis, 2, np.nan), _shift(codes, axis, 2, 0)
        slope_a = np.where(ca2 == codes, z - a2, np.nan)[edge]
        slope_b = np.where(cb2 == cb, b2 - b, np.nan)[edge]
        both = np.stack([slope_a, slope_b])
        known = np.isfinite(both).sum(axis=0)
        slope = np.where(known > 0, np.nansum(both, axis=0) / np.maximum(known, 1), 0.0)
        delta = (b[edge] - z[edge]) - slope                  # b's surface relative to a's at the edge
        ca, cbe = codes[edge], cb[edge]
        ia, ib = flat[edge], _shift(flat, axis, 1, -1)[edge]
        sides += [(ca, cbe, ia, delta / 2), (cbe, ca, ib, -delta / 2)]
        if pairs is not None:
            own = np.ones(len(delta), bool) if count is None else count[edge]
            lo, hi = np.minimum(ca, cbe)[own], np.maximum(ca, cbe)[own]
            offset = np.where(ca[own] == lo, delta[own], -delta[own])   # the higher code's surface
            for key in set(zip(lo.tolist(), hi.tolist())):
                sel = (lo == key[0]) & (hi == key[1])
                entry = pairs.setdefault(key, [0, 0.0, 0.0])
                entry[0] += int(sel.sum())
                entry[1] += float(offset[sel].sum())
                entry[2] += float(np.abs(offset[sel]).sum())
    if not sides:
        return elevation.copy(), np.zeros(z.shape, dtype=bool)
    own_code, other_code, cell, half = (np.concatenate(part) for part in zip(*sides))
    correction = np.zeros(z.shape)
    for mine, theirs in sorted(set(zip(own_code.tolist(), other_code.tolist()))):
        sel = (own_code == mine) & (other_code == theirs)
        total, n = np.zeros(z.size), np.zeros(z.size)
        np.add.at(total, cell[sel], half[sel])
        np.add.at(n, cell[sel], 1.0)
        edge_cells = (n > 0).reshape(z.shape)
        values = np.where(n > 0, total / np.maximum(n, 1), 0.0).reshape(z.shape)
        num = ndimage.gaussian_filter(values, sigma_cells, mode='constant')
        den = ndimage.gaussian_filter(edge_cells.astype(np.float64), sigma_cells, mode='constant')
        # distance of the cell centre from the boundary line (half a cell beyond the boundary cell's centre)
        across = (ndimage.distance_transform_edt(~edge_cells) + 0.5) * cell_m
        target = (codes == mine) & (across < feather_m) & (den > 1e-9)
        v = (across[target] + feather_m) / (2 * feather_m)
        correction[target] += 2.0 * (1.0 - v * v * (3.0 - 2.0 * v)) * num[target] / den[target]
    result = (z + correction).astype(np.float32)
    result[codes == 0] = elevation[codes == 0]
    return result, result != elevation


def feather_raster(depth_path, codes_path, target_path, *, feather_m=FEATHER_M, block=512):
    """Windowed seam_feather over whole rasters; each block reads a halo so the result is block-independent."""
    from rasterio.windows import Window
    pairs, changed, largest = {}, 0, 0.0
    # Halo: gaussian radius (scipy truncate 4 sigma) + taper reach + the 2-cell slope stencil + 1 margin.
    halo = int(4 * SEAM_SIGMA_CELLS + 0.5) + math.ceil(feather_m / 10) + 3
    with rasterio.open(depth_path) as depth, rasterio.open(codes_path) as codes:
        profile = depth.profile.copy()
        with rasterio.open(target_path, 'w', **profile) as out:
            for row in range(0, depth.height, block):
                for col in range(0, depth.width, block):
                    r0, c0 = max(row - halo, 0), max(col - halo, 0)
                    r1, c1 = min(row + block + halo, depth.height), min(col + block + halo, depth.width)
                    window = Window(c0, r0, c1 - c0, r1 - r0)
                    values, chosen = depth.read(1, window=window), codes.read(1, window=window)
                    core = (slice(row - r0, min(row + block, depth.height) - r0),
                            slice(col - c0, min(col + block, depth.width) - c0))
                    own = np.zeros(values.shape, dtype=bool)
                    own[core] = True
                    blended, moved = seam_feather(values, chosen, feather_m=feather_m, pairs=pairs, count=own)
                    changed += int(moved[core].sum())
                    if moved[core].any():
                        largest = max(largest, float(np.abs(blended[core] - values[core])[moved[core]].max()))
                    out.write(blended[core], 1, window=Window(col, row, core[1].stop - core[1].start,
                                                               core[0].stop - core[0].start))
    return pairs, changed, largest


def mosaic(region_file, sources_file, output, *, reserve_gib=250, max_cells=250_000_000, feather_m=FEATHER_M):
    """feather_m=0 turns the seam feather off (hard finest-first boundaries, the pre-MB-02 output)."""
    if isinstance(feather_m, bool) or not isinstance(feather_m, (int, float)) or not math.isfinite(feather_m) \
            or not (feather_m == 0 or 5 < feather_m <= 200):
        raise ValueError('feather_m must be 0 (off) or a finite width above half a cell, at most 200 m')
    region_file, sources_file = Path(region_file).resolve(), Path(sources_file).resolve()
    region = json.loads(region_file.read_text())
    bounds = region['bounds']
    if (len(bounds) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in bounds)
            or not -180 <= bounds[0] < bounds[2] <= 180
            or not -90 <= bounds[1] < bounds[3] <= 90):
        raise ValueError('Invalid WGS84 region bounds')
    projected = transform_bounds('EPSG:4326', 'EPSG:3310', *bounds, densify_pts=101)
    west, south = [math.floor(x / 10) * 10 for x in projected[:2]]
    east, north = [math.ceil(x / 10) * 10 for x in projected[2:]]
    width, height = int((east - west) / 10), int((north - south) / 10)
    cells = width * height
    if cells > max_cells or not cells:
        raise ValueError('Segment exceeds cell cap')
    if not math.isfinite(reserve_gib) or reserve_gib < 0:
        raise ValueError('Reserve must be nonnegative and finite')
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError('Use a fresh output directory; existing artifacts are never overwritten')
    ancestor = output.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    sources = load_sources(sources_file)
    # Materialized source grids + final/intermediate COGs and overviews.
    estimated_bytes = cells * (40 + 4 * len(sources))
    if shutil.disk_usage(ancestor).free - estimated_bytes < reserve_gib * 1024**3:
        raise ValueError('Free-space reserve would be crossed')
    output.mkdir(parents=True)
    work = output / 'work'
    work.mkdir()
    gdal = GDAL()
    warped = []
    for row in sources:
        normal = work / f'{row["code"]}-normalized.vrt'
        target = work / f'{row["code"]}-warped.tif'
        normalized_vrt(row, normal)
        # Materialize once: lazy warped VRTs can choose different approximation
        # chunks when read through a stack versus direct contributor windows.
        gdal.run('Warp', target, [normal], ['-of', 'GTiff', '-et', 0,
                 '-co', 'TILED=YES', '-co', 'COMPRESS=DEFLATE',
                 '-t_srs', 'EPSG:3310',
                 '-te', west, south, east, north, '-tr', 10, 10, '-r', 'near',
                 '-ot', 'Float32', '-dstnodata', NODATA, '-wo', 'INIT_DEST=NO_DATA'])
        warped.append(target)
    # GDAL's LAST valid source wins: reverse the finest-first logical priority.
    stack = work / 'priority-stack.vrt'
    gdal.run('BuildVRT', stack, list(reversed(warped)),
             ['-strict', '-resolution', 'user', '-tr', 10, 10, '-srcnodata', NODATA,
              '-vrtnodata', NODATA])
    depth_work = work / 'elevation.tif'
    gdal.run('Warp', depth_work, [stack], ['-of', 'GTiff', '-t_srs', 'EPSG:3310',
             '-te', west, south, east, north, '-tr', 10, 10, '-r', 'near',
             '-ot', 'Float32', '-dstnodata', NODATA, '-co', 'TILED=YES',
             '-co', 'COMPRESS=DEFLATE', '-co', 'BIGTIFF=IF_SAFER'])
    counts = {str(row['code']): 0 for row in sources}
    band_counts = dict(counts)
    stats = dict(grid_cells=cells, valid_cells=0, hole_cells=0, overlap_cells=0,
                 extra_source_cell_observations=0, minimum_elevation_m=None, maximum_elevation_m=None)
    contributor_work, support_work = work / 'contributor.tif', work / 'support_count.tif'
    with ExitStack() as context:
        depth = context.enter_context(rasterio.open(depth_work, 'r+'))
        grids = [context.enter_context(rasterio.open(p)) for p in warped]
        profile = depth.profile.copy()
        profile.update(dtype='uint16', nodata=0)
        contributor = context.enter_context(rasterio.open(contributor_work, 'w', **profile))
        support = context.enter_context(rasterio.open(support_work, 'w', **profile))
        for _, window in depth.block_windows(1):
            elevation = depth.read(1, window=window)
            chosen = np.zeros(elevation.shape, dtype='uint16')
            coverage = np.zeros(elevation.shape, dtype='uint16')
            expected = np.full(elevation.shape, NODATA, dtype='float32')
            for row, grid in zip(sources, grids):
                values = grid.read(1, window=window)
                mask = (values != np.float32(NODATA)) & np.isfinite(values)
                take = mask & (chosen == 0)
                chosen[take], expected[take] = row['code'], values[take]
                coverage += mask.astype('uint16')
            valid = chosen > 0
            if not np.array_equal(elevation, expected):
                bad = elevation != expected
                raise ValueError(f'Depth/contributor mismatch at {window}: '
                                 f'{int(bad.sum())} cells; actual={elevation[bad][:8].tolist()}; '
                                 f'expected={expected[bad][:8].tolist()}')
            contributor.write(chosen, 1, window=window)
            support.write(coverage, 1, window=window)
            nvalid = int(valid.sum())
            stats['valid_cells'] += nvalid
            stats['hole_cells'] += int((~valid).sum())
            stats['overlap_cells'] += int((coverage > 1).sum())
            stats['extra_source_cell_observations'] += int(np.maximum(coverage.astype('int32') - 1, 0).sum())
            unique, freq = np.unique(chosen, return_counts=True)
            for code, count in zip(unique, freq):
                if code:
                    counts[str(code)] += int(count)
        for grid in (depth, contributor, support):
            grid.update_tags(description=LABEL, vertical_reference='mixed_source_references_explicit_offsets_only',
                             value_convention='elevation_positive_up' if grid is depth else 'source_code_or_count')
    if not stats['valid_cells']:
        raise ValueError('No valid source cells inside segment')
    seams = dict(feather_m=feather_m, changed_cells=0, max_abs_change_m=0.0, boundaries=[])
    if feather_m:
        blended = work / 'elevation-feathered.tif'
        pairs, seams['changed_cells'], largest = feather_raster(depth_work, contributor_work, blended,
                                                               feather_m=feather_m)
        seams['max_abs_change_m'] = round(largest, 4)
        ids = {row['code']: row['id'] for row in sources}
        seams['boundaries'] = [dict(sources=[ids[lo], ids[hi]], edges=n, mean_offset_m=round(total / n, 4),
                                    mean_abs_offset_m=round(absolute / n, 4))
                               for (lo, hi), (n, total, absolute) in sorted(pairs.items())]
        with rasterio.open(blended, 'r+') as grid:
            grid.update_tags(description=LABEL, vertical_reference='mixed_source_references_explicit_offsets_only',
                             value_convention='elevation_positive_up',
                             seam_feather=f'{feather_m:g} m elevation feather at contributor boundaries')
        depth_work = blended
    # Elevation statistics and the 0-300 ft band describe the delivered (feathered) elevation.
    with rasterio.open(depth_work) as depth, rasterio.open(contributor_work) as contributor:
        for _, window in depth.block_windows(1):
            elevation, chosen = depth.read(1, window=window), contributor.read(1, window=window)
            valid = chosen > 0
            if valid.any():
                low, high = float(elevation[valid].min()), float(elevation[valid].max())
                stats['minimum_elevation_m'] = min(low, stats['minimum_elevation_m']) if stats['minimum_elevation_m'] is not None else low
                stats['maximum_elevation_m'] = max(high, stats['maximum_elevation_m']) if stats['maximum_elevation_m'] is not None else high
            in_band = valid & (elevation <= 0) & (elevation >= np.float32(-BAND_LIMIT_M))
            for code, count in zip(*np.unique(chosen[in_band], return_counts=True)):
                band_counts[str(code)] += int(count)
    outputs = {}
    for name, path in [('elevation', depth_work), ('contributor', contributor_work), ('support_count', support_work)]:
        target = output / f'{name}.tif'
        raster_copy(path, target, driver='COG', compress='DEFLATE', blocksize=512,
                    overview_resampling='NEAREST', BIGTIFF='IF_SAFER')
        with rasterio.open(target) as grid:
            if grid.tags(ns='IMAGE_STRUCTURE').get('LAYOUT') != 'COG':
                raise ValueError('Output is not a COG')
        outputs[name] = dict(path=target.name, sha256=file_hash(target), bytes=target.stat().st_size)
    manifest = dict(schema_version=1, status='review_required', navigation=LABEL,
                    segment=region['id'], region_sha256=file_hash(region_file),
                    source_table_sha256=file_hash(sources_file), crs='EPSG:3310', resolution_m=10,
                    bounds_wgs84=bounds, bounds_projected=[west, south, east, north],
                    width=width, height=height, value_convention='elevation_positive_up', units='m',
                    vertical_reference='mixed_source_references_explicit_offsets_only',
                    priority='finest native resolution first; lexical id ties; GDAL last-valid stack reversed',
                    resampling='nearest (no cross-source interpolation)', gdal_version=rasterio.__gdal_version__,
                    seam_feather=dict(seams, method='one smoothstep across the 2 x feather_m band centred on every '
                                                    '4-neighbour boundary between two contributors; the offset is '
                                                    'estimated per edge (step minus local slope) and smoothed along '
                                                    'the boundary; cells with no survey are never filled',
                                      along_boundary_sigma_m=SEAM_SIGMA_CELLS * 10,
                                      contributor='contributor.tif keeps the winning source of every cell, '
                                                  'including cells changed by the feather'),
                    sources=sources, outputs=outputs, stats=stats, contributor_cells=counts,
                    band_0_300ft=dict(limit_m=91.44, cells=sum(band_counts.values()),
                                      km2=round(sum(band_counts.values()) * 100 / 1e6, 4),
                                      contributor_cells=band_counts,
                                      note='10 m cells whose chosen elevation is 0 to -91.44 m; holes (land or unsurveyed) are not classified'),
                    limitations=['Hole cells include land and unsurveyed water; no water mask was supplied.',
                                 'No seamless vertical-datum reconciliation is claimed; constant offsets are not VDatum.',
                                 'The seam feather is a display blend within feather_m of a source boundary, '
                                 'not a datum reconciliation; offsets between surveys remain in the data.',
                                 'Unstated datum uses zero offset and is explicitly unresolved.',
                                 'Bounding box is conservatively enclosed in the projected rectangular grid.',
                                 'Not a navigation, rights-clearance, or semantic acceptance.'])
    json_write(output / 'manifest.json', manifest)
    # COGs are self-contained; remove derived intermediates, never the cached originals.
    shutil.rmtree(work)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reserve-gib', type=float, default=250)
    parser.add_argument('--max-cells', type=int, default=250_000_000)
    parser.add_argument('--feather-m', type=float, default=FEATHER_M,
                        help='seam feather width at contributor boundaries in metres; 0 = hard boundaries')
    args = parser.parse_args()
    result = mosaic(args.region, args.sources, args.output, reserve_gib=args.reserve_gib, max_cells=args.max_cells,
                    feather_m=args.feather_m)
    print(json.dumps({'segment': result['segment'], 'status': result['status'], **result['stats']}))


if __name__ == '__main__':
    main()

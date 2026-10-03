#!/usr/bin/env python3
"""Independently reconcile original beams and private MB-System median grids.

This research stage writes a measured-support COG, not a catalog promotion,
habitat classification, coverage credit or fishing export. Run beside private
originals; provider paths and commands are evidence and are never executed.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from pyproj import Transformer

from research.scripts.triage_multibeam_beams import COLUMNS, validate_reader_receipt

MAX_BYTES = 256_000_000
MAX_PIXELS = 10_000_000
MAX_ROWS = 4_000_000
MBGRID_SHA = '9ebca2e54b861c333e97ac0bdf89d3f89b7bcc2d8bfe50f496ba17d540ceea33'
MBLIST_SHA = '8292e93e456b3d547f61cc30ae3c488bfae188318910f365eaffdfb181223802'


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def bounded_lines(path, max_bytes=MAX_BYTES):
    opener = gzip.open if Path(path).suffix == '.gz' else open
    used = 0
    with opener(path, 'rb') as stream:
        while line := stream.readline(1_000_001):
            used += len(line)
            if used > max_bytes or len(line) > 1_000_000:
                raise ValueError('Input exceeds decompressed byte/line bound')
            yield line


def read_grid(path):
    lines = iter(bounded_lines(path))
    header, digest = {}, hashlib.sha256()
    for _ in range(6):
        try:
            line = next(lines); key, value = line.split()
            key = key.decode().lower(); value = float(value)
        except (StopIteration, ValueError) as error:
            raise ValueError('Malformed ASCII grid header') from error
        digest.update(line)
        if key in header or not math.isfinite(value):
            raise ValueError('Invalid ASCII grid header')
        header[key] = value
    if set(header) != {'ncols', 'nrows', 'xllcorner', 'yllcorner', 'cellsize', 'nodata_value'}:
        raise ValueError('Expected explicit corner-registered ASCII grid')
    w, h, size = header['ncols'], header['nrows'], header['cellsize']
    if w != int(w) or h != int(h) or min(w, h, size) <= 0 or w*h > MAX_PIXELS:
        raise ValueError('Invalid/excessive grid dimensions')
    a = np.empty((int(h), int(w)), dtype='float64')
    for y in range(int(h)):
        try:
            line = next(lines)
        except StopIteration as error:
            raise ValueError('Incomplete ASCII grid') from error
        digest.update(line)
        values = line.split()
        if len(values) != int(w):
            raise ValueError('Grid column count differs from header')
        a[y] = [float(value) for value in values]
        if not np.isfinite(a[y]).all():
            raise ValueError('Nonfinite ASCII grid values')
    for line in lines:
        digest.update(line)
        if line.strip():
            raise ValueError('Unexpected extra grid rows')
    return header, a, digest.hexdigest()


def grid_recipe(receipt):
    if receipt.get('returncode') != 0 or receipt.get('binary_sha256') != MBGRID_SHA:
        raise ValueError('Unverified grid executable or failed processing')
    command = receipt.get('command', [])
    if not isinstance(command, list) or not all(isinstance(v, str) for v in command):
        raise ValueError('Malformed grid command')
    indexes = [i for i, v in enumerate(command) if Path(v).name == 'mbgrid']
    if len(indexes) != 1:
        raise ValueError('Missing exact grid executable')
    options = command[indexes[0]+1:]
    for value in ('-A2', '-F2', '-C0', '-G4', '-M', '-P1', '-U0'):
        if options.count(value) != 1:
            raise ValueError('Grid must preserve full topography/median/count/no-fill recipe')
    allowed = {'-A2', '-F2', '-C0', '-G4', '-M', '-P1', '-N', '-V', '-U0'}
    patterns = [r'-I.+', r'-O.+', r'-R[-+.0-9/]+',
                r'-E[0-9.]+/[0-9.]+meters!', r'-JUTM[0-9]{2}[NS]']
    for pattern in patterns:
        if sum(bool(re.fullmatch(pattern, v)) for v in options) != 1:
            raise ValueError('Missing/duplicate bounded grid parameter')
    if any(v not in allowed and not any(re.fullmatch(p, v) for p in patterns) for v in options):
        raise ValueError('Unsupported grid processing option')
    projection = next(v for v in options if v.startswith('-J'))
    zone = int(projection[5:7]); north = projection[-1] == 'N'
    if not 1 <= zone <= 60:
        raise ValueError('Invalid UTM zone')
    spacing = next(v[2:-7] for v in options if v.startswith('-E')).split('/')
    if len(spacing) != 2 or float(spacing[0]) != float(spacing[1]) or float(spacing[0]) <= 0:
        raise ValueError('Grid requires exact positive square bins')
    bounds = [float(v) for v in next(v[2:] for v in options if v.startswith('-R')).split('/')]
    if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds) or not (-180 <= bounds[0] < bounds[1] <= 180 and -90 <= bounds[2] < bounds[3] <= 90):
        raise ValueError('Invalid bounded geographic window')
    return (32600 if north else 32700) + zone, float(spacing[0])


def reconcile(header, topography, count, dispersion, beams, *, epsg):
    """Reproduce documented MB-System integer binning and upper median.

    MB-System truncates its integer bin coordinates towards zero. This differs
    from floor immediately outside the south/west grid edge. Such bins and bins
    ambiguous at printed-header precision remain excluded from safe support.
    """
    h, w = topography.shape; size = header['cellsize']; total = h*w
    lon, lat, depth = beams.T
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    cx = (x-header['xllcorner'])/size; cy = (y-header['yllcorner'])/size
    col = np.trunc(cx).astype('int64'); bottom = np.trunc(cy).astype('int64')
    inside = (col >= 0) & (col < w) & (bottom >= 0) & (bottom < h)
    keys = (h-1-bottom[inside])*w+col[inside]; z = -depth[inside]
    order = np.lexsort((z, keys)); k, z = keys[order], z[order]
    ids, starts, counts = np.unique(k, return_index=True, return_counts=True)
    expected_count = np.zeros(total, dtype='float64'); expected_count[ids] = counts
    expected_z = np.full(total, np.nan); expected_z[ids] = z[starts+counts//2]
    minimum = np.full(total, np.nan); maximum = minimum.copy()
    minimum[ids] = -z[starts+counts-1]; maximum[ids] = -z[starts]
    residual = (z-np.repeat(expected_z[ids], counts))**2
    sums = np.add.reduceat(residual, starts) if len(ids) else np.array([])
    expected_sd = np.zeros(total); expected_sd[ids] = np.sqrt(sums/np.maximum(counts-1, 1))
    grid_valid = np.isfinite(topography.ravel()) & (topography.ravel() != header['nodata_value'])
    supported = expected_count > 0
    supplied_count = np.where(count.ravel() == header['nodata_value'], 0, count.ravel())
    # The pinned ASCII writer uses %.10g. Withhold both possible neighbors
    # of every printed-corner rounding boundary, without fitting a grid shift.
    def rounding_bound(value):
        return .5 * 10**(math.floor(math.log10(abs(value)))-9) if value else 0.
    tx = rounding_bound(header['xllcorner'])/size
    ty = rounding_bound(header['yllcorner'])/size
    ambiguous = np.zeros(total, dtype=bool)
    # Corner precision plus conservative numerical projection roundoff only.
    for dx in (-tx-1e-9, tx+1e-9):
        for dy in (-ty-1e-9, ty+1e-9):
            alternate_col = np.trunc(cx+dx).astype('int64')
            alternate_bottom = np.trunc(cy+dy).astype('int64')
            altered = ((alternate_col != col) | (alternate_bottom != bottom)
                       | (cx < 0) | (cy < 0))
            alternate_inside = ((alternate_col >= 0) & (alternate_col < w)
                                & (alternate_bottom >= 0) & (alternate_bottom < h))
            selected = altered & alternate_inside
            ambiguous[(h-1-alternate_bottom[selected])*w+alternate_col[selected]] = True
            selected = altered & inside
            ambiguous[(h-1-bottom[selected])*w+col[selected]] = True
    checked = ~ambiguous
    support_mismatch = int(((grid_valid != supported) & checked).sum())
    count_mismatch = int(((supplied_count != expected_count) & checked).sum())
    mismatches = support_mismatch + count_mismatch
    if mismatches:
        raise ValueError(f'Original beam/count/support parity failed: {mismatches} cells '
                         f'(support={support_mismatch}, count={count_mismatch}, '
                         f'beam_total={len(keys)}, grid_total={supplied_count.sum()}, '
                         f'ambiguous={ambiguous.sum()})')
    if np.any(supplied_count < 0) or not np.isfinite(supplied_count).all() or np.any(supplied_count != np.trunc(supplied_count)):
        raise ValueError('Invalid sounding count values')
    check = supported & checked
    if np.any(dispersion.ravel()[grid_valid] < 0):
        raise ValueError('Negative sounding dispersion')
    if (not np.isfinite(dispersion.ravel()[check]).all()
            or np.any(np.abs(topography.ravel()[check]-expected_z[check]) > .0001)
            or np.any(np.abs(dispersion.ravel()[check]-expected_sd[check]) > .0051)):
        raise ValueError('Original median or dispersion parity failed')
    # Good depths were NOT prefiltered at 91.44 m before binning. Exclude bins
    # whose original contributors cross zero or the nominal depth ceiling.
    crossing = supported & (((minimum <= 91.44) & (maximum > 91.44))
                            | ((minimum <= 0) & (maximum > 0)))
    safe = supported & grid_valid & checked & ~crossing
    shape = (h, w)
    # Both readers print decimal depths at different precision. After the
    # unchanged grid/table parity check, retain the table-derived order statistic
    # with its own contributor extrema. Mixing the supplied rounded grid median
    # with table extrema can place a median outside its range after float32
    # storage. This does not recover unprinted source precision or repair beams.
    median_delta = np.abs(topography.ravel()[check]-expected_z[check])
    arrays = [-expected_z.reshape(shape), expected_count.reshape(shape), dispersion,
              minimum.reshape(shape), maximum.reshape(shape)]
    return arrays, safe.reshape(shape), {
        'original_good_beams_in_grid': int(len(keys)), 'occupied_bins': int(supported.sum()),
        'nominal_shallow_representative_bins': int((supported & (-expected_z > 0) & (-expected_z <= 91.44)).sum()),
        'mixed_depth_boundary_bins': int(crossing.sum()),
        'registration_ambiguous_bins': int(ambiguous.sum()),
        'safe_nominal_shallow_bins': int((safe & (minimum > 0) & (maximum <= 91.44)).sum()),
        'independently_checked_bins': int(check.sum()),
        'count_support_mismatches': 0,
        'stored_depth_basis': 'reconciled complete printed beam-table order statistic',
        'maximum_grid_table_median_difference_m': float(median_delta.max()) if median_delta.size else 0.,
        'median_method': 'upper order statistic of positive-up topography (not middle-pair average)',
        'dispersion_method': 'sample RMS around selected median, not calibrated uncertainty'}


def prepare(grid_paths, receipt_path, beam_pairs, native_root, output):
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.shutil import copy as raster_copy
    receipt_path, output, native_root = Path(receipt_path), Path(output), Path(native_root)
    if receipt_path.stat().st_size > 1_000_000:
        raise ValueError('Grid receipt exceeds bound')
    raw_receipt = receipt_path.read_bytes(); receipt = json.loads(raw_receipt)
    epsg, spacing = grid_recipe(receipt)
    sources = receipt.get('inputs', [])
    if not 0 < len(sources) <= 8 or len(sources) != len(beam_pairs):
        raise ValueError('Incomplete original source/beam set')
    native = {}
    for source in sources:
        name = Path(source['path']).name
        if name in native or not re.fullmatch(r'.+\.mb[0-9]+', name):
            raise ValueError('Duplicate/invalid native source')
        p = native_root/name
        if p.stat().st_size != source['bytes'] or file_hash(p) != source['sha256']:
            raise ValueError('Original native source checksum mismatch')
        native[name] = source['sha256']
    outputs = {v['path']: v['sha256'] for v in receipt['outputs']}
    if len(outputs) != len(receipt['outputs']):
        raise ValueError('Duplicate grid output identities')
    options = receipt['command'][next(i for i,v in enumerate(receipt['command']) if Path(v).name == 'mbgrid')+1:]
    grid_root = Path(next(v[2:] for v in options if v.startswith('-O'))).name
    expected_names = [grid_root+'.asc', grid_root+'_num.asc', grid_root+'_sd.asc']
    if [Path(v).name.removesuffix('.gz') for v in grid_paths] != expected_names:
        raise ValueError('Grid roles differ from recorded output root')
    grids, headers, hashes = [], [], []
    for path in grid_paths:
        header, values, digest = read_grid(path)
        name = Path(path).name.removesuffix('.gz')
        if outputs.get(name) != digest:
            raise ValueError('Grid output checksum mismatch')
        headers.append(header); grids.append(values); hashes.append(digest)
    if len(grids) != 3 or any(h != headers[0] for h in headers) or headers[0]['cellsize'] != spacing:
        raise ValueError('Paired grid alignment/spacing mismatch')
    seen, parts, table_hashes = set(), [], []
    total_rows = 0
    for table, metadata_path in beam_pairs:
        if Path(metadata_path).stat().st_size > 1_000_000:
            raise ValueError('Beam receipt exceeds bound')
        meta = json.loads(Path(metadata_path).read_bytes()); validate_reader_receipt(meta)
        if meta.get('columns') != COLUMNS or meta['binary_sha256'] != MBLIST_SHA:
            raise ValueError('Unverified original beam reader/columns')
        name = Path(next(v[2:] for v in meta['command'] if v.startswith('-I'))).name
        if name not in native or name in seen:
            raise ValueError('Beam tables do not match original grid source set')
        seen.add(name); digest = hashlib.sha256(); points = []; rows = 0
        for line in bounded_lines(table):
            digest.update(line)
            if not line.strip(): continue
            v = [float(x) for x in line.split()]; rows += 1; total_rows += 1
            if total_rows > MAX_ROWS or len(v) != 7 or not all(math.isfinite(x) for x in v):
                raise ValueError('Malformed/excessive beam table')
            if not (-180 <= v[0] <= 180 and -90 <= v[1] <= 90):
                raise ValueError('Invalid beam coordinates')
            if not all(x >= 0 and x.is_integer() for x in (v[3], v[5], v[6])):
                raise ValueError('Invalid beam flag/identifier')
            if v[3] == 0: points.append(v[:3])
        if rows != meta['rows'] or digest.hexdigest() != meta['stdout_sha256']:
            raise ValueError('Complete original beam table checksum/row mismatch')
        parts.append(np.asarray(points).reshape(-1, 3)); table_hashes.append(digest.hexdigest())
    if sum(len(p) for p in parts) > MAX_ROWS:
        raise ValueError('Combined beams exceed row bound')
    arrays, safe, stats = reconcile(headers[0], *grids, np.concatenate(parts), epsg=epsg)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.with_suffix('.json').exists():
        raise ValueError('Refusing to overwrite prior private processing')
    temporary = output.with_suffix('.working.tif'); part = output.with_suffix('.part.tif')
    h = headers[0]; transform = from_origin(h['xllcorner'], h['yllcorner']+h['nrows']*spacing, spacing, spacing)
    try:
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(temporary, 'w', driver='GTiff',
                width=int(h['ncols']), height=int(h['nrows']), count=5, dtype='float32', crs=f'EPSG:{epsg}',
                transform=transform, nodata=np.nan, tiled=True, blockxsize=512, blockysize=512,
                compress='DEFLATE') as ds:
            for band, (a, label) in enumerate(zip(arrays, ['depth_m_positive_down', 'original_good_sounding_count',
                    'median_dispersion_m_not_uncertainty', 'contributor_depth_min_m', 'contributor_depth_max_m']), 1):
                ds.write(np.where(safe, a, np.nan).astype('float32'), band); ds.set_band_description(band, label)
            ds.write_mask(safe.astype('uint8')*255)
            ds.update_tags(depth_basis='nominal', vertical_datum=receipt.get('depth_datum', 'unknown'),
                sampling='irregular original soundings', grid_spacing_basis='derived bin spacing, not native resolution',
                source_qualification='pending', fishing_export='prohibited', interpolation='none')
        raster_copy(temporary, part, driver='COG', COMPRESS='DEFLATE', BLOCKSIZE=512, OVERVIEWS='NONE')
        part.replace(output)
    finally:
        temporary.unlink(missing_ok=True); part.unlink(missing_ok=True)
    result = {'observed_at': datetime.now(timezone.utc).isoformat(), 'scope': 'private-multibeam-grid-parity',
        'grid_receipt_sha256': hashlib.sha256(raw_receipt).hexdigest(), 'originals': native,
        'beam_table_sha256': table_hashes, 'grid_sha256': hashes, 'output_sha256': file_hash(output),
        'horizontal_crs': f'EPSG:{epsg}', 'derived_bin_spacing_m': spacing, **stats,
        'native_resolution': 'irregular soundings', 'uncertainty': 'unknown', 'vertical_datum': receipt.get('depth_datum', 'unknown'),
        'source_qualified': False, 'fishing_target': False, 'exportable': False,
        'new_measured_km2': 0, 'new_physical_candidates': 0, 'new_public_locations': 0}
    from skippercast.platform.contracts import atomic_json
    atomic_json(output.with_suffix('.json'), result, indent=2)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--topography', type=Path, required=True); p.add_argument('--count', type=Path, required=True)
    p.add_argument('--dispersion', type=Path, required=True); p.add_argument('--grid-receipt', type=Path, required=True)
    p.add_argument('--beam', nargs=2, action='append', metavar=('TABLE', 'RECEIPT'), required=True)
    p.add_argument('--native-root', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(prepare([a.topography, a.count, a.dispersion], a.grid_receipt, a.beam, a.native_root, a.output)))


if __name__ == '__main__':
    main()

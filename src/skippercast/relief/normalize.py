"""R2: normalise a held local DEM without granting rights or inferring measurement.

An optional ``support_adapters.ADAPTERS[family]`` is a SupportAdapter. Its
classifier receives the open original dataset, a native Grid, and the declared
external evidence paths. It must read no undeclared evidence. For VR BAG the
Grid's ``refinement`` identifies the native (south-origin row, column); elevation
and validity arrays, including refinement arrays, are always north-up for BAG.
"""
from contextlib import nullcontext
from dataclasses import dataclass, replace
import argparse
import importlib
import json
import math
import os
from pathlib import Path
import re
from collections.abc import Callable

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio import Affine
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.shutil import copy as copy_raster
from rasterio.transform import array_bounds, from_origin
from rasterio.warp import Resampling, reproject, transform_bounds, transform_geom

from skippercast.util.units import M_PER_FT

from . import receipts

NODATA = np.float32(-np.finfo('float32').max)
MAX_CELLS = 100_000_000
VALUE_UP, VALUE_DOWN = 'elevation_positive_up', 'depth_positive_down'
LOWER = {'interpolated': 1, 'compiled': 1, 'unknown': 2, 'measured': 3}


@dataclass(frozen=True)
class Grid:
    elevation: np.ndarray
    valid: np.ndarray
    transform: Affine
    crs: CRS
    refinement: tuple[int, int] | None = None


@dataclass(frozen=True)
class SupportAdapter:
    id: str
    classify: Callable
    # Additional implementation files (helpers or a separate science policy).
    code_files: tuple[Path, ...] = ()


def adapter_for(family):
    name = f'{__package__}.support_adapters'
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        return None, None, {}
    adapter = module.ADAPTERS.get(family)
    if adapter is None:
        return None, None, {}
    implementation = importlib.import_module(adapter.classify.__module__)
    files = tuple(dict.fromkeys(Path(p).resolve() for p in
                  (module.__file__, implementation.__file__, *adapter.code_files) if p is not None))
    pins = {p: receipts.sha256_file(p) for p in files}
    identity = (adapter.classify.__module__, adapter.classify.__qualname__, list(pins.values()))
    digest = receipts.sha256_bytes(receipts.canonical(identity))
    return adapter, {'id': adapter.id, 'digest': digest}, pins


def horizontal(crs):
    return crs.sub_crs_list[0] if crs.is_compound else crs


def target_crs(source, bounds):
    if source.utm_zone and source.axis_info[0].unit_conversion_factor == 1:
        return source
    west, south, east, north = transform_bounds(source, 'EPSG:4326', *bounds)
    if -80 <= south < north <= 84 and -180 <= west < east <= 180 and not south < 0 < north:
        zone = min(60, 1 + math.floor(((west + east) / 2 + 180) / 6))
        boundary = -180 + (zone - 1) * 6
        if west >= boundary - 1e-9 and east <= boundary + 6 + 1e-9:
            geographic = source.geodetic_crs
            # (code base, last zone): EPSG defines NAD83 UTM zones 1-23N but
            # NAD83(2011) UTM zones only 1-19N (6330-6348); zones 20-23 for
            # NAD83(2011) fall through to the WGS 84 UTM zone below.
            nad83_utm = {4269: (26900, 23), 6318: (6329, 19)}.get(geographic.to_epsg())
            if south >= 0 and nad83_utm is not None and 1 <= zone <= nad83_utm[1]:
                return CRS.from_epsg(nad83_utm[0] + zone)
            return CRS.from_epsg((32600 if south >= 0 else 32700) + zone)
    return CRS.from_epsg(3310)


def semantics(ds, original, convention):
    tags = {k.lower(): v for k, v in (ds.tags() | ds.tags(1)).items()}
    vertical = next((c for c in original.sub_crs_list if c.is_vertical), None)
    declared = tags.get('vertical_datum', '')
    name = ' '.join((vertical.name, vertical.datum.name)) if vertical else declared
    normalized = re.sub(r'[^A-Z0-9]', '', name.upper())
    datum = next((value for key, value in (
        ('NAVD88', 'NAVD88'), ('NORTHAMERICANVERTICALDATUM1988', 'NAVD88'),
        ('MEANLOWERLOWWATER', 'MLLW'), ('MLLW', 'MLLW'), ('MEANSEALEVEL', 'MSL'),
        ('MSL', 'MSL'), ('EGM2008', 'EGM2008'), ('INSTANTANEOUSSEALEVEL', 'instantaneous_sea_level'))
                  if key in normalized), 'unstated')
    axis = vertical.axis_info[0] if vertical else None
    units = ds.units[0] or tags.get('units') or tags.get('unittype')
    if units:
        scale = {'m': 1, 'metre': 1, 'meter': 1, 'metres': 1, 'meters': 1,
                 'ft': M_PER_FT, 'foot': M_PER_FT, 'feet': M_PER_FT,
                 'us survey foot': 1200 / 3937}.get(units.lower().strip())
        if scale is None:
            raise ValueError(f'unsupported elevation unit: {units}')
    else:
        scale = axis.unit_conversion_factor if axis else 1
    # The BAG elevation and refinement values are positive-up by format even
    # when the vertical CRS is specified as a depth (positive-down) axis.
    convention = convention or tags.get('value_convention') or (
        VALUE_DOWN if ds.driver != 'BAG' and (tags.get('positive', '').lower() == 'down'
                                             or (axis and axis.direction == 'down')) else VALUE_UP)
    if convention not in {VALUE_UP, VALUE_DOWN}:
        raise ValueError('unknown source value convention')
    return dict(vertical_datum=datum, source_vertical_datum=name or 'unstated',
                source_units=units or (axis.unit_name if axis else 'unstated (metres assumed)'),
                source_value_convention=convention, unit_to_m=scale)


def make_grid(raw, valid, transform, crs, meta, scale=1, offset=0, refinement=None):
    sign = -1 if meta['source_value_convention'] == VALUE_DOWN else 1
    factor = meta['unit_to_m'] * sign
    values = raw.astype('float32', copy=True)
    if scale != 1 or offset != 0 or factor != 1:
        # Never apply scale/offset to a stored nodata sentinel.
        values[~valid] = 0
        values = (values * scale + offset) * factor
    valid = valid & np.isfinite(values) & (values != NODATA)
    values[~valid] = NODATA
    return Grid(values, valid, transform, crs, refinement)


def spacing(grid, destination):
    t = grid.transform
    x, y = grid.elevation.shape[1] / 2, grid.elevation.shape[0] / 2
    points = [t * p for p in [(x, y), (x + 1, y), (x, y + 1)]]
    if grid.crs == destination:
        return max(math.hypot(t.a, t.d), math.hypot(t.b, t.e))
    xy = Transformer.from_crs(grid.crs, destination, always_xy=True).transform(*zip(*points))
    center, right, down = zip(*xy)
    return max(math.dist(center, right), math.dist(center, down))


def grid_bounds(grid):
    h, w = grid.elevation.shape
    return array_bounds(h, w, grid.transform)


def layout(grids, destination, resolution):
    if len(grids) == 1:
        g = grids[0]
        t = g.transform
        if g.crs == destination and t.a == -t.e == resolution and not (t.b or t.d):
            return g.transform, g.elevation.shape
    bounds = [transform_bounds(g.crs, destination, *grid_bounds(g)) for g in grids]
    west, south = min(b[0] for b in bounds), min(b[1] for b in bounds)
    east, north = max(b[2] for b in bounds), max(b[3] for b in bounds)
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError('invalid native spacing')
    if grids[0].refinement is not None:
        # Keep the finest refinement on its original lattice when the CRS and
        # spacing allow it. Coarser blocks must not shift that lattice.
        for grid in grids:
            t = grid.transform
            if grid.crs == destination and t.a == -t.e == resolution:
                west = t.c + math.floor((west - t.c) / resolution + 1e-9) * resolution
                north = t.f + math.ceil((north - t.f) / resolution - 1e-9) * resolution
                break
    width = math.ceil((east - west) / resolution - 1e-9)
    height = math.ceil((north - south) / resolution - 1e-9)
    if width < 1 or height < 1 or width * height > MAX_CELLS:
        raise ValueError('regular output exceeds the cell limit or has empty bounds')
    return from_origin(west, north, resolution, resolution), (height, width)


def read_footprints(path):
    if path is None:
        return []
    doc = json.loads(path.read_text())  # GeoJSON, RFC 7946 (WGS84)
    if doc.get('type') != 'FeatureCollection':
        raise ValueError('footprints must be a GeoJSON FeatureCollection')
    return [(f['geometry'], LOWER[f['properties']['label']]) for f in doc['features']
            if f['properties']['label'] != 'measured']


def classify(ds, grid, adapter, evidence, label, footprints):
    cap = LOWER.get(label, 3)
    if adapter is None and not footprints:
        return min(2, cap)
    if adapter is None:
        classes = np.full(grid.valid.shape, 2, dtype='uint8')
    else:
        classes = np.asarray(adapter.classify(ds, grid, evidence))
        if (classes.shape != grid.valid.shape or classes.dtype != np.uint8
                or np.any(classes > 3) or np.any(grid.valid & (classes == 0))):
            raise ValueError('adapter must return aligned uint8 classes 1–3 on valid cells')
        classes = classes.copy()
    np.minimum(classes, cap, out=classes)
    for geometry, cap in footprints:
        if geometry['type'] not in {'Polygon', 'MultiPolygon'}:
            raise ValueError('support footprint must be a polygon')
        native = transform_geom('EPSG:4326', grid.crs.to_wkt(), geometry)
        within = geometry_mask([native], grid.valid.shape, grid.transform, invert=True, all_touched=True)
        classes[within] = np.minimum(classes[within], cap)
    classes[~grid.valid] = 0
    return classes


def warp(grid, classes, transform, shape, destination):
    if (grid.crs == destination and grid.elevation.shape == shape
            and grid.transform.almost_equals(transform, precision=1e-8)):
        return grid.elevation, np.where(grid.valid, classes, 0).astype('uint8')
    kwargs = dict(src_transform=grid.transform, src_crs=grid.crs.to_wkt(),
                  dst_transform=transform, dst_crs=destination.to_wkt(), resampling=Resampling.bilinear)
    data = np.full(shape, NODATA, dtype='float32')
    reproject(grid.elevation, data, src_nodata=float(NODATA), dst_nodata=float(NODATA), **kwargs)
    output_valid = np.isfinite(data) & (data != NODATA)
    data[~output_valid] = NODATA
    if np.isscalar(classes):
        return data, np.where(output_valid, classes, 0).astype('uint8')
    # Bilinear weights are nonnegative. A positive result for an indicator
    # means that the same elevation kernel touched at least one such cell.
    # Masked cells limit certification to 2, but do not hide a class-1 neighbor.
    support = np.full(shape, 3, dtype='uint8')
    for flag, cap in ((classes < 3, 2), (classes == 1, 1)):
        if flag.any():
            influence = np.zeros(shape, dtype='float32')
            reproject(flag.astype('float32'), influence, **kwargs)
            support[influence > 0] = cap
    support[~output_valid] = 0
    return data, support


def bag_grids(bag, ds, source, meta):
    """Read only native refinement nodes, not the low-resolution overview."""
    metadata, records = bag['varres_metadata'], bag['varres_refinements']
    required = {'index', 'dimensions_x', 'dimensions_y', 'resolution_x', 'resolution_y', 'sw_corner_x', 'sw_corner_y'}
    if (metadata.shape != ds.shape or not required <= set(metadata.dtype.names or ())
            or records.ndim != 2 or records.shape[0] != 1 or 'depth' not in (records.dtype.names or ())
            or metadata.size > MAX_CELLS or records.size > MAX_CELLS
            or ds.transform.b or ds.transform.d or ds.transform.a <= 0 or ds.transform.e >= 0):
        raise ValueError('unsupported VR BAG layout')
    m = metadata[:]
    active = (m['dimensions_x'] > 0) & (m['dimensions_y'] > 0)
    rows, cols = np.nonzero(active)
    starts = m['index'][active].astype('int64')
    lengths = m['dimensions_x'][active].astype('int64') * m['dimensions_y'][active]
    order = np.argsort(starts)
    ends = starts + lengths
    if (not len(order) or np.any((m['dimensions_x'] > 0) != (m['dimensions_y'] > 0))
            or np.any(lengths <= 0) or starts[order[0]] != 0 or max(ends) > records.size
            or np.any(starts[order[1:]] != ends[order[:-1]])):
        raise ValueError('malformed VR BAG refinement ranges')
    depth = records.fields('depth')[0, :int(max(ends))]
    for row, col, start, end in zip(rows, cols, starts, ends):
        block = m[row, col]
        nx, ny = int(block['dimensions_x']), int(block['dimensions_y'])
        dx, dy, sx, sy = (float(block[k]) for k in
                          ('resolution_x', 'resolution_y', 'sw_corner_x', 'sw_corner_y'))
        cx, cy = ds.res
        if (not all(math.isfinite(v) for v in (dx, dy, sx, sy)) or min(dx, dy) <= 0
                or min(sx, sy) < -1e-3 or sx + (nx - 1) * dx > cx + 1e-3
                or sy + (ny - 1) * dy > cy + 1e-3):
            raise ValueError('invalid VR BAG refinement geometry')
        raw = depth[start:end].reshape(ny, nx)[::-1]
        valid = np.isfinite(raw) & (raw != 1_000_000)
        if valid.any():
            # BAG SW corners locate the first node center, relative to its parent cell edge.
            left = ds.bounds.left + col * cx + sx - dx / 2
            top = ds.bounds.bottom + row * cy + sy + (ny - 0.5) * dy
            yield make_grid(raw, valid, from_origin(left, top, dx, dy), source, meta,
                            refinement=(int(row), int(col)))


def regularize(ds, grids, destination, transform, shape, resolution, adapter, evidence, label, footprints):
    data = np.full(shape, NODATA, dtype='float32')
    support = np.zeros(shape, dtype='uint8')
    # Fine blocks own overlaps, including their holes; never blend across a refinement edge.
    for native_spacing, grid in sorted(grids, key=lambda pair: -pair[0]):
        west, south, east, north = transform_bounds(grid.crs, destination, *grid_bounds(grid))
        inv = ~transform
        col0, row0 = inv * (west, north)
        col1, row1 = inv * (east, south)
        x0, y0 = max(0, math.floor(col0)), max(0, math.floor(row0))
        x1, y1 = min(shape[1], math.ceil(col1)), min(shape[0], math.ceil(row1))
        if x1 <= x0 or y1 <= y0:
            continue
        sub = transform * Affine.translation(x0, y0)
        size = (y1 - y0, x1 - x0)
        classes = classify(ds, grid, adapter, evidence, label, footprints)
        if native_spacing > resolution * (1 + 1e-6):
            classes = np.minimum(classes, 2)  # Fine output spacing cannot certify coarse input support.
        values, mask = warp(grid, classes, sub, size, destination)
        owned = np.zeros(size, dtype='uint8')
        reproject(np.ones(grid.valid.shape, dtype='uint8'), owned,
                  src_transform=grid.transform, src_crs=grid.crs.to_wkt(),
                  dst_transform=sub, dst_crs=destination.to_wkt(), resampling=Resampling.nearest)
        take = owned.astype(bool)
        data[y0:y1, x0:x1][take] = values[take]
        support[y0:y1, x0:x1][take] = mask[take]
    return data, support


def write_cog(path, values, crs, transform, nodata, tags):
    with MemoryFile() as mem, mem.open(driver='GTiff', height=values.shape[0], width=values.shape[1],
                                      count=1, dtype=values.dtype, crs=crs.to_wkt(),
                                      transform=transform, nodata=nodata) as ds:
        ds.write(values, 1)
        ds.update_tags(**tags)
        if values.dtype == np.float32:
            ds.set_band_unit(1, 'm')
        # Use full-resolution support only; a nearest/averaged overview is not evidence.
        copy_raster(ds, path, driver='COG', COMPRESS='DEFLATE', LEVEL=1, OVERVIEWS='NONE')


def fingerprint(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


def write_normalized(source, output, params, source_sha, code_digest, adapter, evidence, footprints):
    if source.suffix.lower() == '.bag':
        import h5py
        container = h5py.File(source, 'r')
    else:
        container = nullcontext()
    with container as hdf, rasterio.Env(GDAL_PAM_ENABLED='NO', PROJ_NETWORK='OFF'):
        options = {'MODE': 'LOW_RES_GRID'} if hdf is not None else {'GEOREF_SOURCES': 'INTERNAL'}
        with rasterio.open(source, **options) as ds:
            if ds.driver != ('BAG' if hdf is not None else 'GTiff') or not ds.crs or not ds.count:
                raise ValueError('expected a georeferenced local GeoTIFF or BAG')
            blue = params['family'] in {'bluetopo', 'nbs_bluetopo'}
            if (blue and (ds.driver != 'GTiff' or ds.count != 3)) or (not blue and ds.driver == 'GTiff' and ds.count != 1):
                raise ValueError('expected a one-band DEM or a three-band BlueTopo source')
            if ds.width * ds.height > MAX_CELLS:
                raise ValueError('source exceeds the cell limit')
            original = CRS.from_user_input(ds.crs)
            src_crs = horizontal(original)
            dest = target_crs(src_crs, ds.bounds)
            meta = semantics(ds, original, params['source_value_convention'])
            bag = hdf['BAG_root'] if hdf is not None else None
            vr = bag is not None and 'varres_refinements' in bag and bag['varres_refinements'].size > 0
            if vr:
                grids = list(bag_grids(bag, ds, src_crs, meta))
                if not grids:
                    raise ValueError('VR BAG has no valid refinement cells')
            else:
                raw = ds.read(1)
                valid = (ds.read_masks(1) != 0) & np.isfinite(raw)
                if ds.nodatavals[0] is not None:
                    valid &= raw != ds.nodatavals[0]
                grids = [make_grid(raw, valid, ds.transform, src_crs, meta, ds.scales[0], ds.offsets[0])]
            with_spacing = [(spacing(g, dest), g) for g in grids]
            resolution = min(r for r, _ in with_spacing)
            transform, shape = layout(grids, dest, resolution)
            caps = read_footprints(footprints)
            label = params['label']
            if vr:
                data, support = regularize(ds, with_spacing, dest, transform, shape, resolution,
                                           adapter, evidence, label, caps)
            else:
                grid = grids[0]
                support_in = classify(ds, grid, adapter, evidence, label, caps)
                data, support = warp(grid, support_in, transform, shape, dest)
            ignored = [dict(band=i, role=role, description=ds.descriptions[i - 1])
                       for i, role in ([(2, 'uncertainty'), (3, 'contributor')] if blue else
                                       ([(2, 'uncertainty')] if ds.driver == 'BAG' and ds.count >= 2 else []))]
            sidecar = dict(schema='sc-relief-normalized/1', original_sha256=source_sha, params=params,
                           normalizer_digest=code_digest, source_crs=original.to_wkt(),
                           source_transform=list(ds.transform)[:6], source_band=1, ignored_bands=ignored,
                           source_scale=ds.scales[0], source_offset=ds.offsets[0], variable_resolution_bag=vr,
                           crs=dest.to_string(), transform=list(transform)[:6], shape=list(shape),
                           resolution_m=resolution, units='m', value_convention=VALUE_UP, **meta)
    write_cog(output / 'grid.tif', data, dest, transform, float(NODATA),
              dict(vertical_datum=meta['vertical_datum'], value_convention=VALUE_UP))
    write_cog(output / 'support.tif', support, dest, transform, 0, {})
    sidecar['outputs'] = {name: receipts.sha256_file(output / name) for name in ('grid.tif', 'support.tif')}
    receipts.write_json_atomic(output / 'sidecar.json', sidecar)


def normalize(source, cache, *, family='dem', convention=None, label=None, footprints=None, evidence=(), region=None):
    """Return the shared-cache StageRun result; optionally bind it to a regional receipt."""
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {'.tif', '.tiff', '.bag'}:
        raise ValueError('source must be a local TIFF or BAG file')
    if label is not None and label not in LOWER:
        raise ValueError('unknown source provenance label')
    evidence = tuple(Path(p).expanduser().resolve() for p in evidence)
    footprints = Path(footprints).expanduser().resolve() if footprints else None
    mask = Path(str(source) + '.msk')
    files = [(source, 'source')]
    if mask.is_file():
        files.append((mask, 'source-mask'))
    if footprints:
        files.append((footprints, 'footprints'))
    files.extend((p, 'support-evidence') for p in evidence)
    adapter, adapter_record, adapter_pins = adapter_for(family)
    stats = [fingerprint(p) if p.is_file() else None for p, _ in files]
    pins = [receipts.sha256_file(p) if stat is not None else None for (p, _), stat in zip(files, stats)]
    source_sha = pins[0]
    if source_sha is None:
        raise ValueError('the original source disappeared before hashing')
    code = receipts.stage_digest([('normalize.py', Path(__file__))])
    params = dict(family=family, label=label, source_value_convention=convention, adapter=adapter_record,
                  dependencies=[dict(role=role, sha256=sha) for (_, role), sha in zip(files[1:], pins[1:])],
                  gdal=rasterio.__gdal_version__)
    key = receipts.sha256_bytes(receipts.canonical(dict(code=code, params=params)))
    cache = Path(cache).expanduser().resolve()
    target = cache / source_sha / key
    shared = receipts.Region(cache / '_receipts' / key, source_sha)

    def produce(output):
        if any(sha is None for sha in pins):
            raise receipts.Held('declared normalization evidence is missing')
        write_normalized(source, output, params, source_sha, code, adapter, evidence, footprints)
        if any(fingerprint(p) != old for (p, _), old in zip(files, stats)) or (
               mask.is_file() != any(role == 'source-mask' for _, role in files)):
            raise ValueError('source or evidence changed during normalization')

    # E2E-01 hashes input roles and bytes for its generation, not path spelling.
    inputs = [receipts.Input(p, role) for (p, role), sha in zip(files, pins) if sha is not None]
    inputs.extend(receipts.Input(p, 'support-adapter-code') for p in adapter_pins)
    plan = receipts.Plan(inputs=inputs, params=dict(params, source_sha256=source_sha))
    run = receipts.StageRun(region=shared, stage='normalize', build=produce, code_digest=code,
                            plan=plan, target=str(target))
    regional_path = region.receipt_path('normalize') if region else None
    with receipts._flock(regional_path.with_suffix('.lock')) if regional_path else nullcontext(True) as acquired:
        if not acquired:
            return receipts.Result('busy', 'normalize', None, None, 'region normalization is running',
                                   shared.receipt_path('normalize'))
        result = receipts.run_stage(run)
        if region and regional_path and result.state != 'busy':
            doc = receipts.read_receipt(shared.receipt_path('normalize'))
            if doc and doc['generation'] == result.generation:
                doc.pop('generation_history', None)
                doc.update(region=region.id, inputs=[dict(row, path=region.record(shared.resolve(row['path'])))
                                                     for row in doc['inputs']])
                receipts.write_json_atomic(regional_path, doc)
                return replace(result, receipt=regional_path)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog='region.py normalize', description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--family', default='dem', help='inventory family key, e.g. nbs_bluetopo')
    parser.add_argument('--region', required=True)
    parser.add_argument('--out', default=os.environ.get('SC_RELIEF_OUT'), required=not os.environ.get('SC_RELIEF_OUT'))
    parser.add_argument('--cache', default=os.environ.get('SC_RELIEF_NORM',
                        '/mnt/agentorange-backup/seafloor-relief-cache/_norm'))
    parser.add_argument('--convention', choices=(VALUE_UP, VALUE_DOWN))
    parser.add_argument('--label', choices=LOWER, help='provenance can only lower support')
    parser.add_argument('--footprints', type=Path, help='WGS84 GeoJSON with properties.label')
    parser.add_argument('--evidence', type=Path, action='append', default=[], help='adapter evidence input, repeatable')
    args = parser.parse_args(argv)
    try:
        region = receipts.Region(args.out, args.region)
        result = normalize(args.source, args.cache, family=args.family, convention=args.convention,
                           label=args.label, footprints=args.footprints, evidence=args.evidence, region=region)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'normalize: {exc}\n')
    print(result.line())
    return result.exit_code

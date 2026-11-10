"""Geographic (lon/lat) elevation GeoTIFF -> metric California Albers grid for the native adapter.

The original adapters need a projected metre grid. Some reviewed originals (USACE NCMP
lidar DEMs on NOAA Digital Coast) are published on a geographic NAD83 grid. This
step projects such a grid, once, into the repository's working projection:

* Horizontal: California Albers (the EPSG:3310 parameters) **on the source's own
  geodetic datum**, so no datum transformation is applied. NAD83 -> EPSG:3310,
  NAD83(2011) -> EPSG:6414. Any other datum (WGS84 included) is refused: a datum
  change is a reviewed decision, not a silent metre-level shift.
* Vertical: values are the source elevations, unchanged in datum, units and sign.
  A declared vertical unit other than metres is refused, never converted.
* Resampling: bilinear for continuous depth/elevation, nearest for classes. The
  output NoData mask is exactly the containing-source-pixel image of the source
  mask: an output pixel is valid iff its centre lies in a valid source pixel. A
  bilinear value is used only when its whole 2x2 source kernel is valid;
  otherwise the containing pixel's own value is kept, so no value is ever
  blended with NoData and the mask neither grows nor shrinks.
* Cell size: the largest source pixel spacing anywhere on the tile, measured in
  target metres, rounded up to 0.1 m. The grid is never finer than the source.
* Grid origin snapped to whole cells, so tiles of one product align.
* Size guard: at most 150 million output pixels (the adapter's own bound) and
  400 million source pixels; work is done in bounded row strips.

The product is cached next to the source with a receipt that binds the source
sha256, every parameter, this file's hash and the product's file and content
hashes, so a rerun reproduces it bit for bit.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from skippercast.platform.contracts import atomic_json, read_json
from .io import sha256

VERSION = 'geographic-to-california-albers-v1'
MAX_OUTPUT_PIXELS = 150_000_000
MAX_SOURCE_PIXELS = 400_000_000
CELL_STEP_M = 0.1
STRIP_ROWS = 256
# Geodetic CRS (EPSG code) -> California Albers on that same datum.
TARGETS = {4269: 'EPSG:3310',   # NAD83 / California Albers
           6318: 'EPSG:6414'}   # NAD83(2011) / California Albers
RESAMPLING = {'depth': 'bilinear', 'class': 'nearest'}
METRE = {'metre', 'meter', 'metres', 'meters', 'm'}
# Steps that would mean a datum change rather than a pure projection.
DATUM_STEPS = ('helmert', 'hgridshift', 'vgridshift', 'gridshift', 'molodensky', '+proj=cart')


def geographic(dataset):
    return bool(dataset.crs) and CRS.from_user_input(dataset.crs).is_geographic


def _geodetic_code(crs):
    """EPSG code of the source's geodetic CRS, identified by PROJ and cross-checked by datum name."""
    horizontal = crs.geodetic_crs
    code = horizontal.to_epsg(min_confidence=90) if horizontal else None
    if code is None:
        raise ValueError('Geographic raster datum is not identified; refusing to guess it')
    if code not in TARGETS:
        raise ValueError(f'No reviewed same-datum target for {horizontal.name} (EPSG:{code}); '
                         'a datum transformation is not applied silently')
    if horizontal.datum.name != CRS.from_epsg(code).datum.name:
        raise ValueError('Geographic raster datum conflicts with its identified CRS')
    return code, horizontal.datum.name


def plan(dataset, *, kind='depth'):
    """Validate a geographic raster and return the reprojection parameters (no I/O beyond headers)."""
    if not dataset.crs:
        raise ValueError('Reprojection requires a georeferenced raster; source has no CRS')
    crs = CRS.from_user_input(dataset.crs)
    if not crs.is_geographic:
        raise ValueError('Reprojection is only for geographic rasters')
    if kind not in RESAMPLING:
        raise ValueError('Unknown raster kind for resampling')
    horizontal = crs.geodetic_crs
    if any(a.unit_name.lower() not in {'degree', 'degrees'} for a in horizontal.axis_info[:2]):
        raise ValueError('Geographic raster must be in degrees')
    if horizontal.prime_meridian.longitude != 0:
        raise ValueError('Geographic raster must use the Greenwich prime meridian')
    code, datum_name = _geodetic_code(crs)
    target = TARGETS[code]
    if dataset.count != 1:
        raise ValueError('Reprojection expects one elevation band')
    t = dataset.transform
    if t.b or t.d or t.a <= 0 or t.e >= 0:
        raise ValueError('Reprojection requires a north-up geographic raster')
    if dataset.width * dataset.height > MAX_SOURCE_PIXELS:
        raise ValueError('Geographic source exceeds the reprojection size guard')
    west, south, east, north = dataset.bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError('Geographic raster bounds are invalid')
    if (dataset.scales and dataset.scales[0] != 1) or (dataset.offsets and dataset.offsets[0] != 0):
        raise ValueError('Packed elevation values (scale/offset) are not converted silently')
    vertical = next((c for c in crs.sub_crs_list if c.is_vertical), None) if crs.is_compound else None
    vertical_units = 'undeclared'
    if vertical is not None:
        units = {a.unit_name.lower() for a in vertical.axis_info}
        if not units <= METRE:
            raise ValueError('Vertical units are not metres; refusing to convert them silently')
        vertical_units = 'metre'
    band_units = (dataset.units[0] or '').strip().lower() if dataset.units else ''
    if band_units and band_units not in METRE:
        raise ValueError('Band units are not metres; refusing to convert them silently')
    if band_units:
        vertical_units = 'metre'
    forward = Transformer.from_crs(horizontal, target, always_xy=True)
    if any(step in forward.definition for step in DATUM_STEPS):
        raise ValueError('Target would require a datum transformation')
    # Source spacing in target metres at the four corner pixels and the centre.
    dlon, dlat = t.a, -t.e
    spacings = []
    for col, row in ((0, 0), (dataset.width-1, 0), (0, dataset.height-1),
                     (dataset.width-1, dataset.height-1), (dataset.width//2, dataset.height//2)):
        lon, lat = t * (col + .5, row + .5)
        x, y = forward.transform([lon, lon+dlon, lon], [lat, lat, lat-dlat])
        spacings += [math.hypot(x[1]-x[0], y[1]-y[0]), math.hypot(x[2]-x[0], y[2]-y[0])]
    cell = round(math.ceil(round(max(spacings) / CELL_STEP_M, 9)) * CELL_STEP_M, 6)
    left, bottom, right, top = transform_bounds(horizontal, target, west, south, east, north, densify_pts=101)
    ix0, ix1 = math.floor(left / cell), math.ceil(right / cell)
    iy0, iy1 = math.floor(bottom / cell), math.ceil(top / cell)
    width, height = ix1 - ix0, iy1 - iy0
    if width * height > MAX_OUTPUT_PIXELS:
        raise ValueError('Reprojected raster would exceed 150,000,000 pixels; refusing a huge tile')
    return {
        'version': VERSION,
        'source_crs': {'name': crs.name, 'authority': ':'.join(crs.to_authority() or ('unknown', '')),
                       'horizontal': f'EPSG:{code}', 'datum': datum_name},
        'target_crs': target,
        'datum_transformation': 'none: same geodetic datum, projection only',
        'operation': forward.definition,
        'vertical_crs': (f"{vertical.name} ({':'.join(vertical.to_authority() or ('unknown', ''))})"
                         if vertical is not None else 'undeclared in source'),
        'vertical_units': vertical_units,
        'values': 'source elevation; vertical datum, units and sign unchanged',
        'resampling': RESAMPLING[kind],
        'resampling_rule': 'bilinear for continuous depth, nearest for classes',
        'edge_rule': ('output valid iff its centre lies in a valid source pixel; bilinear only with a '
                      'fully valid 2x2 kernel, otherwise the containing pixel value'),
        'area_or_point': dataset.tags().get('AREA_OR_POINT', 'unknown'),
        'source_resolution_deg': [dlon, dlat],
        'source_shape': [dataset.height, dataset.width],
        'source_spacing_m': {'min': min(spacings), 'max': max(spacings)},
        'cell_m': cell,
        'cell_rule': 'max source spacing in target metres, rounded up to 0.1 m (never finer than source)',
        'grid_origin': [ix0 * cell, iy1 * cell],
        'shape': [height, width],
    }


def _strip(dataset, params, inverse, r0, r1, nearest_only):
    cell = params['cell_m']
    left, top = params['grid_origin']
    width = params['shape'][1]
    t = dataset.transform
    rows, cols = np.mgrid[r0:r1, 0:width]
    lon, lat = inverse.transform(left + (cols + .5) * cell, top - (rows + .5) * cell)
    lon, lat = np.asarray(lon, dtype='float64'), np.asarray(lat, dtype='float64')
    fx = (lon - t.c) / t.a
    fy = (lat - t.f) / t.e
    ic, jc = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
    gx, gy = fx - .5, fy - .5
    i0, j0 = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    inside = (ic >= 0) & (ic < dataset.width) & (jc >= 0) & (jc < dataset.height)
    out = np.full(lon.shape, np.nan, dtype='float64')
    stats = {'valid': 0, 'bilinear': 0, 'nearest_edge': 0}
    if not inside.any():
        return out.astype('float32'), stats
    jlo = max(0, int(min(jc[inside].min(), j0[inside].min())))
    jhi = min(dataset.height - 1, int(max(jc[inside].max(), j0[inside].max() + 1)))
    block = dataset.read(1, window=Window(0, jlo, dataset.width, jhi - jlo + 1), masked=True)
    # Convert to float before filling: an integer masked array cannot be filled with NaN.
    data = block.astype('float64').filled(np.nan)
    good = ~np.ma.getmaskarray(block) & np.isfinite(data)

    def take(array, i, j):
        # Indices are clipped only to keep the gather in bounds; callers mask the clipped ones out.
        return array[np.clip(j - jlo, 0, data.shape[0] - 1), np.clip(i, 0, dataset.width - 1)]

    valid = take(good, ic, jc) & inside
    nearest = take(data, ic, jc)
    out[valid] = nearest[valid]
    stats['valid'] = int(valid.sum())
    if not nearest_only:
        in4 = (i0 >= 0) & (i0 + 1 < dataset.width) & (j0 >= 0) & (j0 + 1 < dataset.height)
        k = [(i0, j0), (i0 + 1, j0), (i0, j0 + 1), (i0 + 1, j0 + 1)]
        full = in4 & np.logical_and.reduce([take(good, i, j) for i, j in k])
        wx, wy = gx - i0, gy - j0
        v = [take(data, i, j) for i, j in k]
        bil = (v[0] * (1-wx) * (1-wy) + v[1] * wx * (1-wy) + v[2] * (1-wx) * wy + v[3] * wx * wy)
        out[full] = bil[full]
        stats['bilinear'] = int(full.sum())
        stats['nearest_edge'] = stats['valid'] - stats['bilinear']
    return out.astype('float32'), stats


def content_sha256(path):
    """Hash of the grid (CRS, transform, shape) and its exact float32 values, NaN as NoData."""
    digest = hashlib.sha256()
    with rasterio.open(path) as ds:
        header = {'crs': ':'.join(CRS.from_user_input(ds.crs).to_authority()),
                  'transform': [float(v).hex() for v in list(ds.transform)[:6]],
                  'shape': [ds.height, ds.width]}
        digest.update(json.dumps(header, sort_keys=True).encode())
        for y in range(0, ds.height, STRIP_ROWS):
            values = ds.read(1, window=Window(0, y, ds.width, min(STRIP_ROWS, ds.height - y)))
            values = np.where(np.isnan(values), np.float32(np.nan), values).astype('<f4')
            digest.update(values.tobytes())
    return digest.hexdigest()


def prepare(dataset, source_sha256, directory, *, kind='depth'):
    """Return the cached receipt (with 'path') of the metric grid for a geographic ``dataset``."""
    params = plan(dataset, kind=kind)
    inputs = {'source_sha256': source_sha256, 'kind': kind, 'parameters': params,
              'implementation_sha256': sha256(Path(__file__))}
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    directory = Path(directory)
    output = directory / f'reprojected-{key[:32]}.tif'
    receipt_path = output.with_suffix('.json')
    if output.exists() and receipt_path.exists():
        saved = read_json(receipt_path)
        if saved['inputs'] != inputs or sha256(output) != saved['product_sha256']:
            raise ValueError('Reprojected grid cache failed verification')
        return {**saved, 'path': str(output)}
    target = CRS.from_user_input(params['target_crs'])
    inverse = Transformer.from_crs(target, CRS.from_user_input(dataset.crs).geodetic_crs, always_xy=True)
    height, width = params['shape']
    left, top = params['grid_origin']
    cell = params['cell_m']
    profile = dict(driver='GTiff', dtype='float32', nodata=np.nan, count=1, width=width, height=height,
                   crs=target, transform=rasterio.Affine(cell, 0, left, 0, -cell, top),
                   tiled=True, blockxsize=512, blockysize=512, compress='DEFLATE', BIGTIFF='IF_SAFER')
    temporary = output.with_suffix('.part.tif')
    totals = {'valid': 0, 'bilinear': 0, 'nearest_edge': 0}
    try:
        with rasterio.open(temporary, 'w', **profile) as writer:
            for r0 in range(0, height, STRIP_ROWS):
                r1 = min(height, r0 + STRIP_ROWS)
                values, stats = _strip(dataset, params, inverse, r0, r1, params['resampling'] == 'nearest')
                writer.write(values, 1, window=Window(0, r0, width, r1 - r0))
                for name in totals:
                    totals[name] += stats[name]
            writer.set_band_description(1, 'elevation_as_source')
            writer.update_tags(1, units=params['vertical_units'])
            writer.update_tags(source_sha256=source_sha256, reprojection_version=VERSION,
                               source_crs=params['source_crs']['authority'], target_crs=params['target_crs'],
                               vertical_crs=params['vertical_crs'], vertical_units=params['vertical_units'],
                               resampling=params['resampling'], cell_m=str(cell))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    saved = {'inputs': inputs, **params, 'source_sha256': source_sha256,
             'product_sha256': sha256(output), 'product_bytes': output.stat().st_size,
             'product_content_sha256': content_sha256(output),
             'output_pixels': {'valid': totals['valid'], 'bilinear': totals['bilinear'],
                               'nearest_edge': totals['nearest_edge'], 'total': width * height}}
    atomic_json(receipt_path, saved, indent=2)
    return {**saved, 'path': str(output)}


def provenance(receipt):
    """The receipt fields a reviewer needs, without the cache path or nested inputs."""
    return {k: v for k, v in receipt.items() if k not in {'inputs', 'path'}}


FORMAT = 'geographic-geotiff'


def ingest(row, bounds, *, root=None, fetch=False, local=None):
    """Explicit ``geographic-geotiff`` rows: project, then run the unchanged native adapter.

    ingest.py, raster.py and the adapters are cache-key files (tests/contract/
    test_seafloor_key_files.py), so this path wraps them instead of editing them:
    every existing COG key and reviewed hash stays valid. The native adapter
    normalizes the projected product (its own bounds, size, sign and mask rules);
    the result is then bound to the original source hash in the original's cache
    folder, where run.py looks for it.
    """
    import shutil
    from skippercast.platform.contracts import REPO
    from .adapters import usgs_geotiff
    from .fetch import fetch_source
    from .ingest import ingest as ingest_native
    root = Path(root or REPO)
    if row['kind'] != 'bathymetry' or row['format'] != FORMAT:
        raise ValueError('Geographic reprojection is only for geographic-geotiff bathymetry rows')
    cache = root / 'var/seafloor/cache'
    source, downloaded = fetch_source(row, cache, fetch=fetch, local=local)
    source_sha256 = sha256(source)
    with usgs_geotiff.open_source(source, row) as dataset:
        if not geographic(dataset):
            raise ValueError('geographic-geotiff rows must hold a geographic raster; use usgs-geotiff')
        projected = prepare(dataset, source_sha256, source.parent)
    derived = dict(row, format='usgs-geotiff', archive_member='unknown',
                   sha256=projected['product_sha256'], bytes=projected['product_bytes'])
    native, _, _ = ingest_native(derived, bounds, root=root, local=Path(projected['path']))
    inputs = {'version': VERSION, 'source_sha256': source_sha256, 'archive_member': row['archive_member'],
              'reprojection_product_sha256': projected['product_sha256'], 'native_inputs': native['inputs']}
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    output = source.parent / f'geographic-{key[:32]}.tif'
    receipt_path = output.with_suffix('.json')
    if output.exists() and receipt_path.exists():
        saved = read_json(receipt_path)
        if saved['inputs'] != inputs or sha256(output) != saved['cog_sha256']:
            raise ValueError('Geographic normalized cache failed verification')
        return saved, downloaded, True
    native_folder = cache / projected['product_sha256']
    cogs = [p.with_suffix('.tif') for p in native_folder.glob('*.json')
            if read_json(p).get('cog_sha256') == native['cog_sha256'] and p.with_suffix('.tif').exists()]
    if not cogs:
        raise ValueError('Native COG of the projected grid not found')
    temporary = output.with_suffix('.part.tif')
    try:
        shutil.copyfile(sorted(cogs)[0], temporary)
        if sha256(temporary) != native['cog_sha256']:
            raise ValueError('Copied COG failed hash verification')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    saved = dict(native, inputs=inputs, source_id=row['id'], source_sha256=source_sha256,
                 source_bytes=source.stat().st_size, reprojection=provenance(projected),
                 note=('Original producer-gridded depth on a geographic grid, projected on its own datum to '
                       f"{projected['target_crs']} ({projected['resampling']}, {projected['cell_m']} m cells, never "
                       'finer than the source) and then normalized by the unchanged native adapter; no datum or '
                       'vertical conversion, habitat or legal clearance. native_resolution_m and pixel counts '
                       'describe the projected grid, not native source pixels. Producer supplied no separate '
                       'interpolation mask.'))
    atomic_json(receipt_path, saved, indent=2)
    return saved, downloaded, False

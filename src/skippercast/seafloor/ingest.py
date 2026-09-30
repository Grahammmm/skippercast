"""Original source -> bounded, native-resolution COG and private inspection receipt."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.windows import Window

from skippercast.platform.contracts import REPO, atomic_json, bbox, read_json
from .adapters import bag, usgs_geotiff
from .fetch import fetch_source
from .io import sha256
from .raster import bounds_window, chunks, read_native
from .normalized import raster_identity

VERSION = 'original-native-adapters-v1'


def ingest(row, bounds, *, root=REPO, fetch=False, local=None):
    bbox(list(bounds))
    if row['kind'] != 'bathymetry' or row['format'] not in {'usgs-geotiff', 'bag'}:
        raise ValueError('No original bathymetry adapter for this format')
    cache = Path(root) / 'var/seafloor/cache'
    source, downloaded = fetch_source(row, cache, fetch=fetch, local=local)
    row = deepcopy(row)
    row.update(sha256=sha256(source), bytes=source.stat().st_size)
    key_data = {'source_id': row['id'], 'source_sha256': row['sha256'], 'archive_member': row['archive_member'],
                'format': row['format'], 'vertical_datum': row['vertical_datum'],
                'bounds': list(bounds), 'margin_m': 100, 'version': VERSION,
                'metadata_parser': sha256(Path(__file__).parents[1] / 'platform/bottom_targets.py'),
                'implementation': {name: sha256(Path(__file__).parent / name) for name in
                                   ('ingest.py', 'raster.py', 'adapters/bag.py', 'adapters/usgs_geotiff.py')}}
    key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
    output = source.parent / (key + '.tif')
    receipt_path = output.with_suffix('.json')
    if output.exists() and receipt_path.exists():
        saved = read_json(receipt_path)
        if saved['inputs'] != key_data or sha256(output) != saved['cog_sha256']:
            raise ValueError('Normalized COG cache failed verification')
        if 'raster_identity' not in saved:
            saved['raster_identity'] = raster_identity(output)
            atomic_json(receipt_path, saved, indent=2)
        return saved, downloaded, True
    metadata = {'vertical_datum': row['vertical_datum'], 'uncertainty_type': 'unknown'}
    if row['format'] == 'bag':
        survey_id = Path(row['url']).name.split('_')[0]
        metadata = bag.inspect_metadata(source, survey_id)
        if row['vertical_datum'] != 'unknown' and metadata['vertical_datum'] != row['vertical_datum']:
            raise ValueError('BAG datum conflicts with manifest; review source metadata')
        row['vertical_datum'] = metadata['vertical_datum']
        adapter = bag
    else:
        adapter = usgs_geotiff
    temporary = output.with_suffix('.working.tif')
    cog_temporary = output.with_suffix('.part.tif')
    valid_count = band_count = 0
    try:
        with adapter.open_source(source, row) as raster:
            window = bounds_window(raster, bounds)
            if window.width * window.height > 150_000_000:
                raise ValueError('Requested output exceeds bound; use a smaller reach window')
            horizontal = CRS.from_user_input(raster.crs).to_2d()
            if row['resolution_m'] != 'unknown' and not np.isclose(max(raster.res), row['resolution_m']):
                raise ValueError('Native resolution conflicts with manifest')
            to_geo = Transformer.from_crs(horizontal, 4326, always_xy=True)
            count = 2 if row['format'] == 'bag' else 1
            profile = dict(driver='GTiff', dtype='float32', nodata=np.nan, count=count,
                           width=int(window.width), height=int(window.height),
                           transform=raster.window_transform(window), crs=horizontal,
                           tiled=True, blockxsize=512, blockysize=512, compress='DEFLATE', BIGTIFF='IF_SAFER')
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(temporary, 'w', **profile) as writer:
                for chunk in chunks(window):
                    native = read_native(raster, chunk, row, uncertainty_band=2 if count == 2 else None)
                    dest = Window(chunk.col_off-window.col_off, chunk.row_off-window.row_off,
                                  chunk.width, chunk.height)
                    writer.write(native.depth_m, 1, window=dest)
                    writer.write_mask(native.valid.astype('uint8') * 255, window=dest)
                    if native.uncertainty_m is not None:
                        writer.write(native.uncertainty_m, 2, window=dest)
                    yy, xx = np.indices(native.depth_m.shape)
                    x, y = native.transform * (xx + .5, yy + .5)
                    lon, lat = to_geo.transform(x, y)
                    inside = (lon >= bounds[0]) & (lon < bounds[2]) & (lat >= bounds[1]) & (lat < bounds[3])
                    valid_count += int((native.valid & inside).sum())
                    band_count += int((native.valid & inside & (native.depth_m > 0) & (native.depth_m <= 91.44)).sum())
                writer.set_band_description(1, 'depth_m_positive_down')
                if count == 2:
                    writer.set_band_description(2, 'producer_uncertainty_m')
                writer.update_tags(source_id=row['id'], source_sha256=row['sha256'],
                                   vertical_datum=row['vertical_datum'], interpolation_mask='unknown',
                                   depth_basis='nominal', adapter_version=VERSION)
            raster_copy(temporary, cog_temporary, driver='COG', COMPRESS='DEFLATE',
                        BLOCKSIZE=512, OVERVIEWS='NONE', BIGTIFF='IF_SAFER')
            cog_temporary.replace(output)
            saved = {'inputs': key_data, 'adapter_version': VERSION,
                     'source_id': row['id'], 'source_sha256': row['sha256'], 'source_bytes': row['bytes'],
                     'cog_sha256': sha256(output), 'cog_bytes': output.stat().st_size,
                     'raster_identity': raster_identity(output),
                     'requested_bounds_wgs84': list(bounds), 'seam_margin_m': 100,
                     'valid_pixels_in_requested_bounds': valid_count,
                     'nominal_0_300ft_pixels_in_requested_bounds': band_count,
                     'native_resolution_m': list(raster.res), 'horizontal_crs': horizontal.to_string(),
                     'vertical_datum': row['vertical_datum'], 'uncertainty_type': metadata['uncertainty_type'],
                     'interpolation_mask': 'unknown', 'depth_basis': 'nominal',
                     'metadata': metadata,
                     'note': 'Original producer-gridded depth; no resampling, datum conversion, habitat or legal clearance. Counts are source pixels, not deduplicated reach coverage. Producer supplied no separate interpolation mask.'}
            atomic_json(receipt_path, saved, indent=2)
            return saved, downloaded, False
    finally:
        temporary.unlink(missing_ok=True)
        cog_temporary.unlink(missing_ok=True)

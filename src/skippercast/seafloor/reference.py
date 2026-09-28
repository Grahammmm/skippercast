"""Bounded, cached BlueTopo reference reads; never original-survey evidence."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from zipfile import ZipFile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
import shapefile
import shapely
from shapely.geometry import Point, box, shape
from shapely.ops import substring, transform

from skippercast.platform.contracts import atomic_json, read_json
from .io import NOAA_PREFIX, sha256, verified_file


def planning_spine(config, cache, fetch=False):
    source = config['coastline']
    path = cache / Path(source['url']).name
    verified_file(source['url'], source['sha256'], path, fetch,
                  allowed_prefix='https://naciscdn.org/naturalearth/', max_bytes=10_000_000)
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    start = Point(project(*config['regions'][0]['start_anchor']))
    end = Point(project(*config['end_anchor']))
    member = source['member']
    with ZipFile(path) as archive:
        reader = shapefile.Reader(**{ext: archive.open(f'{member}.{ext}')
                                    for ext in ('shp', 'shx', 'dbf')})
        candidates = []
        for record in reader.iterShapes():
            if box(*record.bbox).intersects(box(*config['bounds'])):
                geom = transform(project, shape(record.__geo_interface__))
                if geom.geom_type == 'LineString':
                    candidates.append(geom)
    coast = min(candidates, key=lambda g: g.distance(start) + g.distance(end))
    spine = substring(coast, coast.project(start), coast.project(end))
    # substring preserves requested north-to-south orientation even for a reversed source.
    if spine.length < 200_000:
        raise ValueError('Planning coast does not span the requested Central Coast')
    return spine


def scheme_tiles(config, root, cache, fetch=False):
    pin = read_json(root / config['blue_topo_pin'])
    path = cache / Path(pin['scheme_url']).name
    verified_file(pin['scheme_url'], pin['scheme_sha256'], path, fetch, max_bytes=20_000_000)
    selected = []
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = [r[0] for r in db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
        if len(tables) != 1 or not tables[0].startswith('BlueTopo_Tile_Scheme_'):
            raise ValueError('Expected one official BlueTopo tile scheme')
        name = tables[0].replace('"', '""')
        for row in db.execute(f'SELECT * FROM "{name}"'):
            blob = row['geom']
            if blob[:2] != b'GP':
                raise ValueError('Invalid GeoPackage geometry')
            offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 7]
            geom = shapely.from_wkb(blob[offset:])
            if not geom.intersects(box(*config['bounds'])):
                continue
            if not row['GeoTIFF_Link'] or not row['GeoTIFF_SHA256_Checksum']:
                raise ValueError(f"Incomplete reference tile: {row['tile']}")
            selected.append({
                'id': row['tile'], 'url': row['GeoTIFF_Link'],
                'publisher_sha256': row['GeoTIFF_SHA256_Checksum'],
                'delivered_date': row['Delivered_Date'],
                'native_resolution_m': float(str(row['Resolution']).removesuffix('m')), 'bounds': list(geom.bounds),
            })
    if not selected:
        raise ValueError('No reference tiles intersect requested scope')
    return pin, sorted(selected, key=lambda r: r['id'])


def tile_sample(tile, cache, sample_m, fetch=False):
    """Read a COG overview, not its full survey-resolution array.

    The publisher checksum identifies the source; range reads cannot verify it.
    A separate checksum verifies the locally cached derived sample.
    """
    identity = {**tile, 'sample_m': sample_m, 'method': 'nearest-overview-v1'}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    path = cache / 'samples' / f'{key}.npz'
    receipt_path = path.with_suffix('.json')
    if path.exists() and receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt['sample_sha256'] != sha256(path) or receipt['input'] != identity:
            raise ValueError('Reference sample cache failed verification')
        return path, receipt
    if not fetch:
        raise FileNotFoundError(f'Reference sample {tile["id"]} missing; rerun with --fetch')
    if not tile['url'].startswith(NOAA_PREFIX + 'BlueTopo/'):
        raise ValueError('Unexpected reference raster host')
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tiff', GDAL_HTTP_TIMEOUT='45',
                      GDAL_HTTP_MAX_RETRY='2', GDAL_HTTP_RETRY_DELAY='1'):
        with rasterio.open(tile['url']) as raster:
            if raster.descriptions[0] != 'Elevation' or not raster.crs:
                raise ValueError('Unexpected reference elevation band or CRS')
            factor = max(1, int(sample_m / max(raster.res)))
            height, width = math.ceil(raster.height / factor), math.ceil(raster.width / factor)
            elevation = raster.read(1, out_shape=(height, width), masked=True,
                                    resampling=Resampling.nearest).astype('float32')
            affine = raster.transform * Affine.scale(raster.width / width, raster.height / height)
            crs = raster.crs.to_wkt()
            native_shape = list(raster.shape)
            overview_factors = raster.overviews(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    with temporary.open('wb') as stream:
        np.savez_compressed(stream, elevation=elevation.filled(np.nan),
                            transform=np.array(tuple(affine)[:6]), crs=np.array(crs))
    temporary.replace(path)
    receipt = {'input': identity, 'sample_sha256': sha256(path),
               'source_checksum_verification': 'not-verified-range-read',
               'source_native_shape': native_shape, 'sample_shape': [height, width],
               'available_overview_factors': overview_factors,
               'sample_spacing_m': [abs(affine.a), abs(affine.e)], 'vertical_crs': crs}
    atomic_json(receipt_path, receipt)
    return path, receipt


def samples(tiles, cache, sample_m, fetch=False):
    # Bounded requests. Executor.map preserves source order independent of completion order.
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda t: tile_sample(t, cache, sample_m, fetch), tiles))

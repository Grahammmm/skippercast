#!/usr/bin/env python3
"""Check saved North B coarse outputs against a supplied region.json, offline.

Supply the expected SHA-256 for each output (e.g. from the coarse stage's
output records), not hashes derived from the files under audit. Exit 0 for
extent fit, 1 for an extent shortfall, and 2 for invalid input. A fit concerns
only the unbuffered region bounds, not the producer's 1 km halo or any cells'
validity. Raw file bytes are hashed, but pixels and masks are not decoded.
"""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import rasterio as rio
import shapely
from pyproj import Transformer
from pyproj.exceptions import ProjError
from rasterio.errors import RasterioError

from skippercast.relief.receipts import sha256_file

NORTH_B = frozenset({
    'fort-bragg-point-arena',
    'shelter-cove-north-mendocino',
    'humboldt-bay-cape-mendocino',
})
GRID_CRS = 'EPSG:3310'  # coarse.write_coarse uses California Albers metres.


def _sha256_matches(actual, expected, label):
    if actual != expected:
        raise ValueError(f'{label} SHA-256 mismatch: expected {expected}, got {actual}')


def _digest_arg(text):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', text):
        raise argparse.ArgumentTypeError('expected a 64-digit SHA-256 hex digest')
    return text.lower()


def _bbox(value, label):
    if (not isinstance(value, list) or len(value) != 4
            or any(type(v) not in (int, float) for v in value)):
        raise ValueError(f'{label} must be [west, south, east, north] in WGS84')
    west, south, east, north = value
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError(f'{label} must be ordered WGS84 bounds')
    return tuple(value)


def _object(data, label):
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise ValueError(f'{label} must be a JSON object')
    return doc


def _local_file(path):
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError('expected a local regular file')
    return path


def _signature(path):
    st = path.stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def audit(region_config, metadata, metadata_sha256, grid, grid_sha256):
    """Return an extent report for explicitly pinned coarse.json and GeoTIFF files."""
    config = _object(_local_file(region_config).read_bytes(), 'region config')
    region = config.get('id')
    if not isinstance(region, str) or region not in NORTH_B:
        raise ValueError('region config must identify a North B region')
    bounds = _bbox(config.get('bounds'), 'region config bounds')

    saved = _local_file(metadata).read_bytes()
    _sha256_matches(hashlib.sha256(saved).hexdigest(), metadata_sha256, 'coarse metadata')
    doc = _object(saved, 'coarse metadata')
    if doc.get('region') != region or _bbox(doc.get('bbox'), 'coarse bbox') != bounds:
        raise ValueError('coarse metadata region/bbox does not match intended region config')
    cell = doc.get('cell_m')
    if isinstance(cell, bool) or not isinstance(cell, (int, float)) or not math.isfinite(cell) or cell <= 0:
        raise ValueError('coarse metadata cell_m must be finite and positive')

    grid = _local_file(grid)
    signature = _signature(grid)
    _sha256_matches(sha256_file(grid), grid_sha256, 'coarse grid')
    # Use embedded GeoTIFF georeferencing only; unhashed sidecars cannot override it.
    with (
        rio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO'),
        rio.open(grid, driver='GTiff', GEOREF_SOURCES='INTERNAL') as src,
    ):
        if src.crs != rio.crs.CRS.from_string(GRID_CRS):
            raise ValueError(f'coarse grid must have embedded {GRID_CRS} CRS')
        t = src.transform
        if not all(map(math.isfinite, t[:6])) or (t.a, t.b, t.d, t.e) != (cell, 0, 0, -cell):
            raise ValueError('coarse grid must be north-up with square pixels matching cell_m')
        west, south, east, north = envelope = tuple(src.bounds)
        if not all(map(math.isfinite, envelope)) or not (west < east and south < north):
            raise ValueError('coarse grid envelope must be finite and nonempty')
    if _signature(grid) != signature:
        raise ValueError('coarse grid changed during audit')

    # Match coarse.build_coarse before it adds the planning halo: project a
    # densified WGS84 rectangle, not just its four corners. Compare pixel edges.
    project = Transformer.from_crs('EPSG:4326', GRID_CRS, always_xy=True).transform
    target = shapely.transform(shapely.box(*bounds).segmentize(0.02), project, interleaved=False).bounds
    if not all(map(math.isfinite, target)):
        raise ValueError('region bounds do not project to a finite envelope')
    x0, y0, x1, y1 = target
    return {
        'region': region,
        'grid_sha256': grid_sha256,
        'metadata_sha256': metadata_sha256,
        'crs': GRID_CRS,
        'region_bounds_wgs84': bounds,
        'region_envelope_3310': target,
        'grid_envelope_3310': envelope,
        'extent_fits': west <= x0 and south <= y0 and east >= x1 and north >= y1,
        'valid_cell_coverage': 'not_assessed',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region-config', type=Path, required=True, help='intended North B region.json')
    parser.add_argument('--metadata', type=Path, required=True, help='saved coarse.json')
    parser.add_argument('--metadata-sha256', type=_digest_arg, required=True)
    parser.add_argument('--grid', type=Path, required=True, help='saved coarse-3310.tif')
    parser.add_argument('--grid-sha256', type=_digest_arg, required=True)
    try:
        report = audit(**vars(parser.parse_args(argv)))
    except (OSError, ValueError, OverflowError, RasterioError, ProjError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0 if report['extent_fits'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

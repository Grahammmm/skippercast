"""Audit CDFW ds3091 original service tiles across California browse sectors.

This is a coarse 40 m *context* scan of CDFW's predicted nearshore substrate,
not native survey bathymetry or a fishing-target generator. The service's class
table and spatial reference are checked before tile pixels are accepted.
Requires numpy, pylerc and pyproj from the optional GIS environment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import urllib.request

import lerc
import numpy as np
from pyproj import Transformer

BASE = 'https://tiledimageservices2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds3091_cru/ImageServer'
METADATA = 'https://filelib.wildlife.ca.gov/public/BDB/GIS/BIOS/metadata/ds3091.html'
LEVEL = 7
RESOLUTION_M = 40
ORIGIN = (-436528.970884573, 459866.804858047)
CLASSES = {1: 'Hard', 2: 'Soft'}
# Cached tiles are addressed by level/row/column, so they are only meaningful for
# the grid (and operator-pinned edition) recorded in this manifest.
CACHE_MANIFEST = 'grid-identity.json'


def read_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'SkipperCast/0.3 public substrate source audit'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def verify_service(service, classes):
    if service.get('name') != 'biosds3091_cru' or service.get('spatialReference', {}).get('wkid') != 3310:
        raise ValueError('Unexpected CDFW substrate service or spatial reference')
    tile = service['tileInfo']
    if tile['format'] != 'LERC2D' or (tile['rows'], tile['cols']) != (256, 256):
        raise ValueError('Unexpected CDFW tile encoding')
    if tile.get('spatialReference', {}).get('wkid', 3310) != 3310:
        raise ValueError('Unexpected CDFW tile spatial reference')
    origin = tile.get('origin') or {}
    try:
        x, y = float(origin['x']), float(origin['y'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('CDFW tile origin missing; tile addresses cannot be bound') from None
    # Row/column selection below uses the reviewed ORIGIN; any other grid would
    # attribute valid classes to the wrong coast.
    if not (math.isclose(x, ORIGIN[0], abs_tol=1e-3) and math.isclose(y, ORIGIN[1], abs_tol=1e-3)):
        raise ValueError('CDFW tile origin differs from the reviewed grid')
    lod = next((row for row in tile['lods'] if row['level'] == LEVEL), None)
    if not lod or lod['resolution'] != RESOLUTION_M:
        raise ValueError('Unexpected CDFW overview resolution')
    actual = {f['attributes']['Value']: f['attributes'].get('CLASSNAME') for f in classes['features']}
    if actual != CLASSES:
        raise ValueError('CDFW hard/soft class table changed')


def grid_identity(edition=None):
    """The reviewed grid that cached level/row/column paths refer to."""
    return {'service': BASE, 'crs': 'EPSG:3310', 'format': 'LERC2D', 'tile_size': [256, 256],
            'level': LEVEL, 'resolution_m': RESOLUTION_M, 'origin': list(ORIGIN),
            'classes': {str(k): v for k, v in CLASSES.items()}, 'edition': edition}


def bind_cache(cache, identity):
    """Return True when cached tiles may be reused; hold if they belong to another grid.

    Reuse needs a matching grid and a matching operator-pinned immutable edition.
    Without one every tile is refetched; the edition is recorded by
    ``seal_cache`` only after a run with no failures. Nothing is deleted.
    """
    manifest = cache / CACHE_MANIFEST
    grid = {k: v for k, v in identity.items() if k != 'edition'}
    if manifest.exists():
        bound = json.loads(manifest.read_text())
        if {k: v for k, v in bound.items() if k != 'edition'} != grid:
            raise ValueError(f'CDFW tile cache {cache} is bound to a different grid; use a fresh --cache')
        if identity['edition'] is not None and bound.get('edition') == identity['edition']:
            return True
    elif cache.exists() and any(cache.iterdir()):
        raise ValueError(f'CDFW tile cache {cache} has no grid identity; use a fresh --cache')
    cache.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({**grid, 'edition': None}, sort_keys=True) + '\n')
    return False


def seal_cache(cache, identity):
    (cache / CACHE_MANIFEST).write_text(json.dumps(identity, sort_keys=True) + '\n')


def sector_tiles(sectors):
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    by_coast = {}
    stride = RESOLUTION_M * 256
    for sector in sectors['sectors']:
        west, south, east, north = sector['bounds']
        projected = [project(x, y) for x in (west, east) for y in (south, north)]
        xs = [p[0] for p in projected]
        ys = [p[1] for p in projected]
        coast = by_coast.setdefault(sector['coast'], set())
        for col in range(max(0, math.floor((min(xs)-ORIGIN[0])/stride)), math.ceil((max(xs)-ORIGIN[0])/stride)):
            for row in range(max(0, math.floor((ORIGIN[1]-max(ys))/stride)), math.ceil((ORIGIN[1]-min(ys))/stride)):
                coast.add((row, col))
    return by_coast


def tile_stamp(path):
    return path.with_name(path.name + '.edition')


def stamped_edition(path, blob):
    """The edition this exact cached blob was fetched under, or None when unproven."""
    try:
        stamp = json.loads(tile_stamp(path).read_text())
    except (OSError, ValueError):
        return None
    if isinstance(stamp, dict) and stamp.get('sha256') == hashlib.sha256(blob).hexdigest():
        return stamp.get('edition')
    return None


def inspect_tile(row, col, cache, edition=None, reuse=False):
    """Audit one tile, reusing the cached blob only if it was fetched under ``edition``.

    The grid-level manifest edition says what the last complete run sealed, but a
    run over fewer sectors refetches only its own tiles. So each tile carries its
    own stamp (edition + blob hash) and an unstamped or other-edition tile is
    refetched even when the manifest matches.
    """
    path = cache / str(LEVEL) / str(row) / f'{col}.lerc'
    url = f'{BASE}/tile/{LEVEL}/{row}/{col}'
    blob = path.read_bytes() if reuse and edition is not None and path.exists() else b''
    reused = bool(blob) and stamped_edition(path, blob) == edition
    if not reused:
        request = urllib.request.Request(url, headers={'User-Agent': 'SkipperCast/0.3 public substrate source audit'})
        with urllib.request.urlopen(request, timeout=35) as response:
            blob = response.read()
        if not blob.startswith(b'Lerc2') or len(blob) > 500000:
            raise ValueError(f'Unexpected LERC tile {row}/{col}')
    result = lerc.decode(blob)
    # pylerc can return a bare error code instead of a tuple for malformed bytes.
    if (not isinstance(result, tuple) or result[0] != 0 or result[1].shape != (256, 256)
            or (result[2] is not None and result[2].shape != (256, 256))):
        raise ValueError(f'Invalid CDFW tile {row}/{col}')
    values = result[1][result[2]] if result[2] is not None else result[1].ravel()
    if not np.isin(values, [1, 2]).all():
        raise ValueError(f'Unexpected CDFW substrate code {row}/{col}')
    digest = hashlib.sha256(blob).hexdigest()
    if not reused:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Drop the old stamp before replacing bytes; only validated tiles get a new stamp.
        tile_stamp(path).unlink(missing_ok=True)
        path.write_bytes(blob)
        if edition is not None:
            tile_stamp(path).write_text(json.dumps({'edition': edition, 'sha256': digest}) + '\n')
    return {'row': row, 'col': col, 'sha256': digest,
            'hard_cells': int(np.count_nonzero(values == 1)),
            'soft_cells': int(np.count_nonzero(values == 2)), 'bytes': len(blob), 'reused': reused}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    parser.add_argument('--cache', type=Path, default=Path('var/cdfw-ds3091-tiles'))
    parser.add_argument('--output', type=Path, default=Path('var/cdfw-ds3091-tile-audit.json'))
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--edition', help='reviewed immutable ds3091 edition; cached tiles are reused only '
                                           'when it matches the edition the cache was sealed with')
    args = parser.parse_args()
    service = read_json(BASE + '?f=pjson')
    classes = read_json(BASE + '/rasterAttributeTable?f=pjson')
    verify_service(service, classes)
    identity = grid_identity(args.edition)
    reuse = bind_cache(args.cache, identity)
    by_coast = sector_tiles(json.loads(args.sectors.read_text()))
    tiles = set().union(*by_coast.values())
    found, failures = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(inspect_tile, row, col, args.cache, args.edition, reuse): (row, col) for row, col in sorted(tiles)}
        for future in as_completed(pending):
            try:
                found.append(future.result())
            except (OSError, ValueError, RuntimeError) as error:
                failures.append({'tile': pending[future], 'error': str(error)[:160]})
    found.sort(key=lambda item: (item['row'], item['col']))
    output = {'scope': 'cdfw-ds3091-40m-tile-audit', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'metadata_url': METADATA, 'service_url': BASE, 'crs': 'EPSG:3310',
              'resolution_m': RESOLUTION_M, 'grid_identity': identity, 'cache_reused': any(item['reused'] for item in found),
              'class_meaning': {'1': 'predicted hard', '2': 'predicted soft'},
              'limits': ['Rugosity proxy, not direct bottom geology or fish presence.',
                         'Coarse resampling and interpolated shallow white zones; no precise rock edge.',
                         'No depth, MPA or fishing-rule qualification.'],
              'requested_tiles': len(tiles), 'audited_tiles': len(found), 'failures': failures,
              'coasts': {coast: {'requested_tiles': len(points),
                                 'audited_tiles': sum((r['row'], r['col']) in points for r in found),
                                 'hard_cells': sum(r['hard_cells'] for r in found if (r['row'], r['col']) in points),
                                 'soft_cells': sum(r['soft_cells'] for r in found if (r['row'], r['col']) in points)}
                         for coast, points in by_coast.items()},
              'tiles': found}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(',', ':')) + '\n')
    print(f"CDFW ds3091: {len(found)}/{len(tiles)} tiles audited; {len(failures)} failures")
    for coast, row in sorted(output['coasts'].items()):
        print(f"  {coast}: {row['hard_cells']} predicted-hard 40 m pixels, {row['soft_cells']} predicted-soft")
    if failures:
        raise SystemExit(1)
    if args.edition is not None:
        seal_cache(args.cache, identity)


if __name__ == '__main__':
    main()

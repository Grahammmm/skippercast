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
    lod = next((row for row in tile['lods'] if row['level'] == LEVEL), None)
    if not lod or lod['resolution'] != RESOLUTION_M:
        raise ValueError('Unexpected CDFW overview resolution')
    actual = {f['attributes']['Value']: f['attributes'].get('CLASSNAME') for f in classes['features']}
    if actual != {1: 'Hard', 2: 'Soft'}:
        raise ValueError('CDFW hard/soft class table changed')


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


def inspect_tile(row, col, cache):
    path = cache / str(LEVEL) / str(row) / f'{col}.lerc'
    url = f'{BASE}/tile/{LEVEL}/{row}/{col}'
    if not path.exists():
        request = urllib.request.Request(url, headers={'User-Agent': 'SkipperCast/0.3 public substrate source audit'})
        with urllib.request.urlopen(request, timeout=35) as response:
            blob = response.read()
        if not blob.startswith(b'Lerc2') or len(blob) > 500000:
            raise ValueError(f'Unexpected LERC tile {row}/{col}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    blob = path.read_bytes()
    result = lerc.decode(blob)
    if result[0] != 0 or result[1].shape != (256, 256) or (result[2] is not None and result[2].shape != (256, 256)):
        raise ValueError(f'Invalid CDFW tile {row}/{col}')
    values = result[1][result[2]] if result[2] is not None else result[1].ravel()
    if not np.isin(values, [1, 2]).all():
        raise ValueError(f'Unexpected CDFW substrate code {row}/{col}')
    return {'row': row, 'col': col, 'sha256': hashlib.sha256(blob).hexdigest(),
            'hard_cells': int(np.count_nonzero(values == 1)),
            'soft_cells': int(np.count_nonzero(values == 2)), 'bytes': len(blob)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    parser.add_argument('--cache', type=Path, default=Path('var/cdfw-ds3091-tiles'))
    parser.add_argument('--output', type=Path, default=Path('var/cdfw-ds3091-tile-audit.json'))
    parser.add_argument('--workers', type=int, default=12)
    args = parser.parse_args()
    service = read_json(BASE + '?f=pjson')
    classes = read_json(BASE + '/rasterAttributeTable?f=pjson')
    verify_service(service, classes)
    by_coast = sector_tiles(json.loads(args.sectors.read_text()))
    tiles = set().union(*by_coast.values())
    found, failures = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(inspect_tile, row, col, args.cache): (row, col) for row, col in sorted(tiles)}
        for future in as_completed(pending):
            try:
                found.append(future.result())
            except (OSError, ValueError, RuntimeError) as error:
                failures.append({'tile': pending[future], 'error': str(error)[:160]})
    found.sort(key=lambda item: (item['row'], item['col']))
    output = {'scope': 'cdfw-ds3091-40m-tile-audit', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'metadata_url': METADATA, 'service_url': BASE, 'crs': 'EPSG:3310',
              'resolution_m': RESOLUTION_M, 'class_meaning': {'1': 'predicted hard', '2': 'predicted soft'},
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


if __name__ == '__main__':
    main()

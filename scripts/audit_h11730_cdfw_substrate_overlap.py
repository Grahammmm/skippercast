"""Cross-check H11730 rocky camera windows with CDFW's predicted substrate.

The output deliberately omits positions. CDFW ds3091 is a rugosity proxy, not
independent rock ground truth; agreement does not qualify a fishing target.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import math
from pathlib import Path
from zipfile import ZipFile

import lerc
from pyproj import Transformer
import shapefile
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from scripts.audit_cdfw_substrate_tiles import BASE, LEVEL, ORIGIN, RESOLUTION_M

CRUISES = ('f208nc', 'c210nc')
SURVEY = 'H11730'
BLOCKS = {'OffshoreFortRoss', 'OffshoreSaltPoint', 'OffshoreBodegaHead'}
VERIFY_FIELDS = ('camera_archive_sha256', 'camera_windows_deduplicated', 'transects',
                 'cdfw_tile_sha256', 'cdfw_class_counts',
                 'nearest_existing_usgs_hard_context_m_range')


def pixel_location(lon, lat):
    x, y = Transformer.from_crs(4326, 3310, always_xy=True).transform(lon, lat)
    stride = RESOLUTION_M * 256
    col = math.floor((x - ORIGIN[0]) / stride)
    row = math.floor((ORIGIN[1] - y) / stride)
    px = math.floor((x - ORIGIN[0] - col * stride) / RESOLUTION_M)
    py = math.floor((ORIGIN[1] - row * stride - y) / RESOLUTION_M)
    if not 0 <= px < 256 or not 0 <= py < 256:
        raise ValueError('CDFW pixel index outside tile')
    return row, col, py, px


def _reader(raw):
    with ZipFile(io.BytesIO(raw)) as archive:
        shp = next(name for name in archive.namelist() if name.lower().endswith('.shp'))
        shx = next(name for name in archive.namelist() if name.lower().endswith('.shx'))
        return shapefile.Reader(shp=io.BytesIO(archive.read(shp)),
                                shx=io.BytesIO(archive.read(shx)))


def review(pairs, cruise_bytes, expected_hashes, tile_audit, tile_cache, usgs_context):
    if tile_audit.get('service_url') != BASE or tile_audit.get('resolution_m') != RESOLUTION_M or tile_audit.get('failures'):
        raise ValueError('Incomplete or changed CDFW substrate audit')
    known_tiles = {(item['row'], item['col']): item for item in tile_audit['tiles']}
    source_pairs = [p for p in pairs['pair_reviews'] if p['survey_id'] == SURVEY
                    and any(c in p.get('camera_archive_url', '') for c in CRUISES)]
    if not source_pairs:
        raise ValueError('Original H11730 camera/depth pairs missing')
    original = {}
    for cruise in CRUISES:
        raw = cruise_bytes[cruise]
        if sha256(raw).hexdigest() != expected_hashes[cruise]:
            raise ValueError('Original USGS camera archive changed')
        original[cruise] = _reader(raw)
    project = Transformer.from_crs(4326, 32610, always_xy=True).transform
    polygons = [transform(project, shape(f['geometry'])) for f in usgs_context['features']
                if f['properties'].get('block_id') in BLOCKS]
    if not polygons:
        raise ValueError('Existing USGS hard-context polygons missing')
    tree = STRtree(polygons)
    counts = Counter()
    transects = defaultdict(Counter)
    distances = []
    checked_tiles = set()
    seen = set()
    decoded = {}
    for pair in source_pairs:
        cruise = next(c for c in CRUISES if c in pair['camera_archive_url'])
        for transect in pair.get('transects', []):
            if len(transect['camera_record_indices']) != transect['window_count']:
                raise ValueError('Original camera-window count changed')
            for index in transect['camera_record_indices']:
                if (cruise, index) in seen:
                    continue
                seen.add((cruise, index))
                lon, lat = original[cruise].shape(index).points[0]
                if not (-123.80 < lon < -123.65 and 38.84 < lat < 38.97):
                    raise ValueError('Camera window outside bounded Point Arena scope')
                row, col, py, px = pixel_location(lon, lat)
                key = (row, col)
                if key not in known_tiles:
                    raise ValueError('Camera tile missing from complete CDFW audit')
                if key not in decoded:
                    raw = (tile_cache / str(LEVEL) / str(row) / f'{col}.lerc').read_bytes()
                    if sha256(raw).hexdigest() != known_tiles[key]['sha256']:
                        raise ValueError('CDFW tile changed after full audit')
                    status, values, mask = lerc.decode(raw)
                    if status != 0 or values.shape != (256, 256):
                        raise ValueError('CDFW LERC tile changed')
                    decoded[key] = (values, mask)
                values, mask = decoded[key]
                code = int(values[py, px]) if mask is None or mask[py, px] else None
                label = {1: 'predicted_hard', 2: 'predicted_soft', None: 'no_data'}.get(code)
                if label is None:
                    raise ValueError('Unexpected CDFW substrate class')
                counts[label] += 1
                transects[(cruise, str(transect['line']))][label] += 1
                point = transform(project, Point(lon, lat))
                nearest = int(tree.nearest(point))
                distances.append(point.distance(polygons[nearest]))
                checked_tiles.add(key)
    return {'schema_version': 1, 'scope': 'h11730-point-arena-camera-vs-cdfw-predicted-substrate',
            'camera_survey': SURVEY, 'camera_archive_sha256': {c: expected_hashes[c] for c in CRUISES},
            'camera_windows_deduplicated': len(seen),
            'transects': [{'cruise': c, 'line': line, 'windows': sum(v.values()),
                           'cdfw_classes': dict(v)} for (c, line), v in sorted(transects.items())],
            'cdfw_source_url': BASE, 'cdfw_audit_checked_at': tile_audit['checked_at'],
            'cdfw_tile_sha256': [{'row': row, 'col': col, 'sha256': known_tiles[row, col]['sha256']}
                                  for row, col in sorted(checked_tiles)],
            'cdfw_class_counts': dict(counts),
            'nearest_existing_usgs_hard_context_m_range': [round(min(distances), 1), round(max(distances), 1)],
            'nearest_existing_usgs_blocks': sorted(BLOCKS),
            'fishing_target': False, 'exportable': False,
            'limitations': ['CDFW ds3091 is a 40 m resampled rugosity-based prediction and can share underlying sonar with the NOAA survey; it is not independent ground truth.',
                            'Four historical camera transects, not 110 independent reefs or catch sites.',
                            'Existing USGS hard-context polygons are geographically remote from these Point Arena camera windows.',
                            'No rock boundary, current fish presence, current chart/MPA/route clearance, legal permission, ranking or export follows.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairs', type=Path, default=Path('dist/data/noaa-statewide-regular-camera-review.json'))
    parser.add_argument('--cruises', type=Path, default=Path('catalog/usgs-video-cruises.json'))
    parser.add_argument('--camera-cache', type=Path, default=Path('var/usgs-video-cache'))
    parser.add_argument('--tile-audit', type=Path, required=True)
    parser.add_argument('--tile-cache', type=Path, default=Path('var/cdfw-ds3091-tiles'))
    parser.add_argument('--usgs-context', type=Path, default=Path('dist/data/usgs-hard-context-san-francisco.geojson'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify', type=Path, help='Reviewed coordinate-free baseline; changed source evidence fails closed')
    args = parser.parse_args()
    result = review(json.loads(args.pairs.read_text()),
                    {c: (args.camera_cache / f'{c}_video_observations.zip').read_bytes() for c in CRUISES},
                    json.loads(args.cruises.read_text())['archives'],
                    json.loads(args.tile_audit.read_text()), args.tile_cache,
                    json.loads(args.usgs_context.read_text()))
    result['reviewed_at'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.verify:
        prior = json.loads(args.verify.read_text())
        if any(result[field] != prior[field] for field in VERIFY_FIELDS):
            raise ValueError('Point Arena camera/substrate evidence changed; review new receipt before promotion')
    print(json.dumps({'windows': result['camera_windows_deduplicated'],
                      'cdfw_class_counts': result['cdfw_class_counts'],
                      'nearest_usgs_context_m': result['nearest_existing_usgs_hard_context_m_range']}))


if __name__ == '__main__':
    main()

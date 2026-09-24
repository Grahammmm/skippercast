"""Audit one bounded CNRA/SANDAG substrate source lead without publishing polygons.

The state mirror exposes interpreted nearshore classes, but its original dates,
resolution, accuracy and redistribution rights are unresolved. This receipt is
for source discovery only; it cannot create fishing targets or exports.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from scripts.audit_usgs_video_observations import open_original_zip

LAYER = 'https://gis.cnra.ca.gov/arcgis/rest/services/Ocean/CSMW_San_Diego_Nearshore_Seafloor_Substrate/MapServer/0'
BOUNDS = (-117.35, 32.77, -117.30, 32.85)
BAG_SUFFIX = 'H11876_MB_2m_MLLW_2of5.bag'


def fetch(url):
    if url != LAYER + '?f=pjson' and not url.startswith(LAYER + '/query?'):
        raise ValueError('Unreviewed substrate service URL')
    request = urllib.request.Request(url, headers={'User-Agent': 'SkipperCast bounded source audit/1.0'})
    with urllib.request.urlopen(request, timeout=35) as response:
        if response.status != 200 or response.url != url:
            raise ValueError('Substrate service status or redirect changed')
        raw = response.read(6_000_001)
    if not raw or len(raw) > 6_000_000:
        raise ValueError('Missing or oversized substrate source response')
    value = json.loads(raw)
    if 'error' in value:
        raise ValueError('Substrate service returned an error')
    return value, hashlib.sha256(raw).hexdigest(), raw


def query(bounds=BOUNDS):
    if bounds != BOUNDS:
        raise ValueError('Only the reviewed La Jolla discovery scope is configured')
    metadata_url = LAYER + '?f=pjson'
    metadata, metadata_sha, _ = fetch(metadata_url)
    field_names = {field['name'] for field in metadata.get('fields', [])}
    if metadata.get('geometryType') != 'esriGeometryPolygon' or not {'OBJECTID', 'descrip'} <= field_names:
        raise ValueError('Substrate polygon layer identity or schema changed')
    common = {'where': '1=1', 'geometry': ','.join(map(str, bounds)),
              'geometryType': 'esriGeometryEnvelope', 'inSR': '4326',
              'spatialRel': 'esriSpatialRelIntersects'}
    count_url = LAYER + '/query?' + urllib.parse.urlencode({**common, 'returnCountOnly': 'true', 'f': 'json'})
    count, count_sha, _ = fetch(count_url)
    if type(count.get('count')) is not int or not 0 <= count['count'] <= 2000:
        raise ValueError('Substrate count missing or exceeds page limit')
    data_url = LAYER + '/query?' + urllib.parse.urlencode({**common, 'outFields': 'OBJECTID,descrip',
        'returnGeometry': 'true', 'outSR': '4326', 'f': 'geojson'})
    data, data_sha, raw = fetch(data_url)
    features = data.get('features')
    if (data.get('type') != 'FeatureCollection' or not isinstance(features, list)
            or data.get('exceededTransferLimit') or len(features) != count['count']):
        raise ValueError('Incomplete substrate polygon query')
    ids = [f.get('properties', {}).get('OBJECTID') for f in features]
    if len(ids) != len(set(ids)) or any(type(i) is not int for i in ids):
        raise ValueError('Missing or duplicate substrate polygon identities')
    invalid_ids = []
    for feature in features:
        if feature.get('geometry', {}).get('type') not in {'Polygon', 'MultiPolygon'}:
            raise ValueError('Unexpected substrate polygon geometry')
        if not shape(feature['geometry']).is_valid:
            invalid_ids.append(feature['properties']['OBJECTID'])
    receipt = {'metadata_url': metadata_url, 'metadata_sha256': metadata_sha,
        'count_url': count_url, 'count_sha256': count_sha,
        'data_url': data_url, 'data_sha256': data_sha}
    return features, receipt, raw, invalid_ids


def review(features, receipt, pair, camera_raw, invalid_ids=()):
    if pair['camera_archive_sha256'] != hashlib.sha256(camera_raw).hexdigest() \
            or not pair['bag_url'].endswith(BAG_SUFFIX):
        raise ValueError('Original camera/BAG identity changed')
    project = Transformer.from_crs('EPSG:4326', 'EPSG:32611', always_xy=True).transform
    polygons = [(str(f['properties'].get('descrip') or '').strip() or 'unclassified',
                 transform(project, shape(f['geometry']))) for f in features
                if f['properties']['OBJECTID'] not in invalid_ids]
    reader = open_original_zip(camera_raw)
    transects = []
    for row in pair['transects']:
        indices = row['camera_record_indices']
        if len(indices) != row['window_count'] or len(indices) != len(set(indices)):
            raise ValueError('Reviewed camera indices changed')
        distances = []
        nearest_classes = []
        for index in indices:
            location = reader.shape(index).points[0]
            point = transform(project, Point(location))
            nearest = min(polygons, key=lambda p: p[1].distance(point)) if polygons else None
            distances.append(nearest[1].distance(point) if nearest else None)
            nearest_classes.append(nearest[0] if nearest else None)
        transects.append({'date': row['date'], 'line': row['line'], 'historical_camera_windows': len(indices),
            'distance_to_nearest_source_polygon_m_range':
                [round(min(distances), 1), round(max(distances), 1)] if polygons else None,
            'nearest_source_polygon_classes': sorted(set(nearest_classes), key=str)})
    return {'schema_version': 1, 'scope': 'san-diego-nearshore-substrate-source-lead',
        'checked_at': datetime.now(timezone.utc).isoformat(), 'bounds': list(BOUNDS),
        'source_layer': LAYER, 'source_receipt': receipt,
        'source_polygon_count': len(features), 'valid_polygon_count': len(polygons),
        'invalid_polygon_objectids': list(invalid_ids),
        'source_classes': dict(Counter(str(f['properties'].get('descrip') or '').strip() or 'unclassified'
                                       for f in features)),
        'historical_camera_source': pair['camera_archive_url'],
        'historical_camera_sha256': pair['camera_archive_sha256'],
        'original_bag_url': pair['bag_url'], 'original_bag_sha256': pair['bag_sha256'],
        'transects': transects, 'fishing_target': False, 'exportable': False,
        'limitations': [
            'The state mirror credits SANDAG and its partners, but original acquisition dates, resolution, accuracy and redistribution rights remain unverified.',
            'This bounded query does not describe full San Diego coverage; intersecting polygon count is not an area or habitat-quality measure.',
            'A kelp-obscured or unclassified polygon is not hard substrate. Invalid geometries are excluded from distance comparisons and held from promotion.',
            'Polygons this far from the offshore camera transects cannot validate those rocky windows or define their reef boundary.',
            'Current legal, depth, chart, route, source-rights and species screens are required before any fishing target or export.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pairs', type=Path, default=Path('dist/data/noaa-statewide-regular-camera-review.json'))
    p.add_argument('--camera-cache', type=Path, default=Path('var/usgs-video-cache/c0111sc_video_observations.zip'))
    p.add_argument('--raw-output', type=Path, default=Path('var/review/cnra-sandag-la-jolla-substrate.geojson'))
    p.add_argument('--output', type=Path, default=Path('dist/data/cnra-sandag-la-jolla-substrate-review.json'))
    a = p.parse_args()
    rows = json.loads(a.pairs.read_text())['pair_reviews']
    matches = [r for r in rows if r['survey_id'] == 'H11876' and r['bag_url'].endswith(BAG_SUFFIX)]
    if len(matches) != 1:
        raise ValueError('One reviewed H11876 original BAG pair required')
    features, receipt, raw, invalid_ids = query()
    result = review(features, receipt, matches[0], a.camera_cache.read_bytes(), invalid_ids)
    if not a.raw_output.resolve().is_relative_to(Path('var/review').resolve()):
        raise ValueError('Unreviewed raw polygons must remain in var/review')
    a.raw_output.parent.mkdir(parents=True, exist_ok=True)
    a.raw_output.write_bytes(raw)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'source_polygon_count': result['source_polygon_count'],
        'source_classes': result['source_classes'], 'fishing_target': False}))


if __name__ == '__main__':
    main()

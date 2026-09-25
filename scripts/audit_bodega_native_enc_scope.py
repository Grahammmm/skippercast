"""Audit full bounded ENC danger-screen coverage of Bodega native-rock research outlines.

An absence of charted dangers in these selected layers is not route, chart,
legal or fishing-site clearance. Raw NOAA responses remain under var/review/.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from skippercast.platform.contracts import REPO, atomic_json


RAW = {
    'point-reyes-tomales': 'point-reyes-tomales-enc-current.geojson',
    'bodega-original-north': 'bodega-original-north-enc.geojson',
    'reyes-original-south': 'reyes-original-south-enc.geojson',
}
SOURCE = 'https://encdirect.noaa.gov/arcgis/rest/services/encdirect'


def audit(root=REPO, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    region = json.loads((root / 'regions/bodega-point-reyes/region.json').read_text())
    if region['status'] != 'preview' or region['id'] != 'bodega-point-reyes':
        raise ValueError('Expected Bodega research-only preview')
    catalog = json.loads((root / 'catalog/noaa-enc-hazard-scopes.json').read_text())
    configurations = {item['id']: item for item in catalog['scopes']}
    review_boxes, danger_geometries, receipts = [], [], []
    project = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True).transform
    for ident, filename in RAW.items():
        config = configurations[ident]
        path = root / 'var/review' / filename
        raw = path.read_bytes()
        data = json.loads(raw)
        if (config['region_id'] != region['id'] or data.get('scope_id') != ident
                or data.get('bounds') != config['bounds'] or data.get('source_url') != SOURCE
                or len(data.get('query_receipts', [])) != 18
                or sum(row['count'] for row in data['query_receipts']) != len(data.get('features', []))):
            raise ValueError('Incomplete or mismatched ENC scope: ' + ident)
        checked = datetime.fromisoformat(data['checked_at'].replace('Z', '+00:00'))
        if not 0 <= (now - checked).total_seconds() <= 36 * 3600:
            raise ValueError('ENC research scope is stale: ' + ident)
        review_boxes.append(box(*config['bounds']))
        danger_geometries.extend(transform(project, shape(item['geometry'])) for item in data['features'])
        receipts.append({'scope_id': ident, 'checked_at': data['checked_at'],
                         'selected_layer_count': 18, 'feature_records': len(data['features']),
                         'raw_sha256': hashlib.sha256(raw).hexdigest()})
    scope_union = unary_union(review_boxes)
    fishing = box(*region['fishing_bounds'])
    context_path = root / 'dist/data/sf-native-hard-context.geojson'
    context_raw = context_path.read_bytes()
    context = json.loads(context_raw)
    research = []
    for feature in context['features']:
        footprint = shape(feature['geometry']).intersection(fishing)
        if footprint.is_empty:
            continue
        if (feature['properties'].get('fishing_target') is not False
                or feature['properties'].get('exportable') is not False
                or not footprint.difference(scope_union).is_empty):
            raise ValueError('Research outline is promoted or outside the ENC review coverage')
        research.append((feature['properties']['id'], transform(project, footprint)))
    if len(research) != 74:
        raise ValueError('The pinned Bodega original-grid outline count changed')
    tree = STRtree(danger_geometries)
    held = []
    for ident, geometry in research:
        nearby = [int(i) for i in tree.query(geometry.buffer(100))
                  if geometry.distance(danger_geometries[int(i)]) <= 100]
        if nearby:
            held.append({'context_id': ident, 'nearby_charted_feature_records': len(nearby)})
    return {'schema_version': 1, 'scope': 'bodega-original-grid-enc-research-screen',
            'audited_at': now.isoformat(), 'source_url': SOURCE,
            'region_id': region['id'], 'source_context_sha256': hashlib.sha256(context_raw).hexdigest(),
            'scope_receipts': receipts, 'research_outlines_in_region': len(research),
            'outlined_footprints_covered_by_all_scopes': len(research),
            'outlines_near_selected_charted_dangers': held, 'review_buffer_m': 100,
            'status': 'research-screen-only',
            'limitations': 'Three bounded NOAA ENC Direct danger-layer queries are not a certified chart, approach or route clearance. No proximity hit does not prove absence of hazards. Historical survey dangers require identity review. Native bottom, complete current exclusions, date/method rules, access and fish evidence still gate every target. No fishing point, rating, drift or export is approved.'}


if __name__ == '__main__':
    result = audit()
    atomic_json(REPO / 'dist/data/bodega-native-enc-scope-review.json', result)
    print(json.dumps({'outlines': result['research_outlines_in_region'],
                      'near_charted_dangers': len(result['outlines_near_selected_charted_dangers'])}))

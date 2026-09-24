"""Cross-check research-only seabed outlines against a bounded NOAA ENC snapshot.

This is a candidate-review screen, not navigation or legal clearance. A clean
outline remains unpublished until the original cells, complete closures, rules,
route and source rights pass their separate reviews.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, box, shape
from shapely.ops import transform
from shapely.strtree import STRtree


def audit(enc, context, historical, *, buffer_m=100):
    if not enc.get('scope_id') or len(enc.get('query_receipts', [])) != 18:
        raise ValueError('ENC snapshot must identify a scope and contain all 18 checked layers')
    if sum(row['count'] for row in enc['query_receipts']) != len(enc.get('features', [])):
        raise ValueError('ENC feature count does not match layer receipts')
    if buffer_m < 0:
        raise ValueError('Negative review buffer')
    project = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True).transform
    hazards = [transform(project, shape(f['geometry'])) for f in enc['features']]
    if not hazards:
        raise ValueError('Empty ENC danger snapshot needs manual review')
    tree = STRtree(hazards)
    if len(enc.get('bounds', [])) != 4:
        raise ValueError('ENC review bounds are missing')
    bounds = box(*enc['bounds'])
    by_survey = Counter()
    held = []
    for feature in context.get('features', []):
        props = feature['properties']
        footprint = shape(feature['geometry'])
        if not footprint.intersects(bounds):
            continue
        survey = props['survey_id']
        by_survey[survey] += 1
        projected = transform(project, footprint)
        nearby = [int(i) for i in tree.query(projected.buffer(buffer_m))
                  if projected.distance(hazards[int(i)]) <= buffer_m]
        if nearby:
            held.append({'context_id': props['id'], 'survey_id': survey,
                         'charted_dangers_within_buffer': len(nearby)})
    historical_distances = []
    for survey in historical['surveys']:
        for item in survey['hazards']:
            location = Point(item['longitude'], item['latitude'])
            if not bounds.covers(location):
                continue
            point = transform(project, location)
            historical_distances.append({'hazard_id': item['id'],
                'survey_id': survey['survey_id'],
                'nearest_enc_danger_m': round(min(point.distance(g) for g in hazards), 1),
                'reconciled_with_current_chart': False})
    return {'schema_version': 1, 'scope_id': enc['scope_id'],
        'enc_checked_at': enc['checked_at'], 'source_url': enc['source_url'],
        'queried_layers': 18, 'charted_danger_features': len(hazards),
        'review_buffer_m': buffer_m, 'context_outlines_in_scope_by_survey': dict(by_survey),
        'outlines_near_charted_dangers': held,
        'historical_report_dangers': historical_distances,
        'status': 'research-screen-only',
        'limitations': 'No target or route is cleared. ENC Direct is not certified for navigation. The nearest charted feature need not be the same object as a historical DTON. Scope clips and incomplete danger classes cannot certify an area free of hazards. Separate current MPA/special-closure, fishing-rule, source-rights and original-cell review remain required.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enc', type=Path, required=True)
    parser.add_argument('--context', type=Path, default=Path('dist/data/sf-native-hard-context.geojson'))
    parser.add_argument('--historical', type=Path, default=Path('catalog/noaa-survey-hazards.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(*(json.loads(path.read_text()) for path in
                     (args.enc, args.context, args.historical)))
    result['audited_at'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps({'scope_id': result['scope_id'],
        'charted_danger_features': result['charted_danger_features'],
        'context_outlines_in_scope': sum(result['context_outlines_in_scope_by_survey'].values()),
        'outlines_near_dangers': len(result['outlines_near_charted_dangers'])}))


if __name__ == '__main__':
    main()

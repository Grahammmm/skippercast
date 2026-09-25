"""Check private, original-grid-qualified camera windows against dated hazard sources.

The public receipt contains aggregate distances only. It cannot clear a route,
establish a navigable depth, or promote a fishing target.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from scripts.build_usgs_statewide_context import mpa_union
from scripts.refresh_enc_hazards import BASE


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def audit(context, context_raw, reconciliation, enc, hazards, snapshot, report_raw):
    survey = reconciliation.get('original_survey_id')
    expected = sum(row['historical_camera_windows'] for row in reconciliation.get('comparison', [])
                   if row['nbs_status'] == 'locally_qualified_90pct'
                   and row['original_bag_status'] == 'original_locally_qualified_90pct')
    features = context.get('features', [])
    reports = [row for row in hazards.get('surveys', []) if row.get('survey_id') == survey]
    if (not survey or reconciliation.get('fishing_target') is not False
            or context.get('scope') != 'unpublished-historical-camera-window-research'
            or context.get('fishing_target') is not False or context.get('exportable') is not False
            or expected < 1 or len(features) != expected or len(reports) != 1):
        raise ValueError('Exact held original-grid camera evidence required')
    report = reports[0]
    if (report['report_url'] != reconciliation['original_report_url']
            or digest(report_raw) != report['report_sha256']
            or len(report.get('hazards', [])) < 1
            or len({row['id'] for row in report['hazards']}) != len(report['hazards'])):
        raise ValueError('Original survey danger report is missing or changed')
    if (enc.get('source_url') != BASE or enc.get('status') != 'charted-danger-screen-only'
            or len(enc.get('query_receipts', [])) != 18
            or sum(row['count'] for row in enc['query_receipts']) != len(enc.get('features', []))
            or not enc['features']):
        raise ValueError('Complete bounded NOAA ENC danger query required')
    if reconciliation.get('cdfw_mpa_retrieved_at') != snapshot.get('sources', {}).get('mpas', {}).get('data_retrieved_at'):
        raise ValueError('Original-grid and hazard screens used different MPA snapshots')
    west, south, east, north = enc['bounds']
    project = Transformer.from_crs('EPSG:4326',
        f'EPSG:326{int(((west + east) / 2 + 180) // 6) + 1:02d}', always_xy=True).transform
    protected = transform(project, mpa_union(snapshot))
    historical = [transform(project, Point(row['longitude'], row['latitude']))
                  for row in report['hazards']]
    charted = [transform(project, shape(row['geometry'])) for row in enc['features']]
    if any(geom.is_empty for geom in charted):
        raise ValueError('Empty charted danger geometry')
    seen = set()
    historical_distances, charted_distances, mpa_distances = [], [], []
    for feature in features:
        props = feature.get('properties', {})
        if (feature.get('geometry', {}).get('type') != 'Point'
                or props.get('survey_id') != survey
                or props.get('evidence') != 'historical-camera-window-and-original-bag-screen'
                or props.get('fishing_target') is not False or props.get('exportable') is not False
                or props.get('id') in seen):
            raise ValueError('Unreviewed or duplicate camera window')
        seen.add(props['id'])
        lon, lat = feature['geometry']['coordinates']
        if not west <= lon <= east or not south <= lat <= north:
            raise ValueError('ENC request omitted a camera window')
        point = transform(project, Point(lon, lat))
        historical_distances.append(min(point.distance(geom) for geom in historical))
        charted_distances.append(min(point.distance(geom) for geom in charted))
        mpa_distances.append(point.distance(protected))
    rounded = lambda values: [round(min(values), 1), round(max(values), 1)]
    return {'schema_version': 1, 'scope': 'original-vr-camera-historical-and-enc-hazard-gate',
        'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'survey_id': survey, 'original_bag_sha256': reconciliation['original_bag_sha256'],
        'original_report_url': report['report_url'], 'original_report_sha256': report['report_sha256'],
        'private_context_sha256': digest(context_raw),
        'enc_source_url': enc['source_url'], 'enc_checked_at': enc['checked_at'],
        'enc_query_layers': len(enc['query_receipts']), 'enc_features': len(enc['features']),
        'cdfw_mpa_retrieved_at': snapshot['sources']['mpas']['data_retrieved_at'],
        'original_qualified_historical_camera_windows': expected,
        'historical_report_dangers': len(historical),
        'minimum_historical_danger_distance_m_range': rounded(historical_distances),
        'minimum_charted_danger_distance_m_range': rounded(charted_distances),
        'minimum_mpa_distance_m_range': rounded(mpa_distances),
        'windows_within_250m_historical_danger': sum(v <= 250 for v in historical_distances),
        'windows_within_100m_charted_danger': sum(v <= 100 for v in charted_distances),
        'windows_within_100m_mpa': sum(v <= 100 for v in mpa_distances),
        'report_danger_review_hold': True, 'present_chart_and_route_cleared': False,
        'fishing_target': False, 'exportable': False,
        'limitations': [
            'Distances are research proximity checks to historical report and selected ENC Direct features, not navigational safety radii or complete chart clearance.',
            'Camera windows are correlated historical observations with variable position accuracy; a point does not delineate a reef or show current fish.',
            'The full survey holiday and rock extents, present certified chart, safe approach, all closures and trip-date rules remain separate gates.',
            'Only aggregate distances are published; the original camera positions remain in the unpublished review cache.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--reconciliation', type=Path, required=True)
    parser.add_argument('--enc', type=Path, required=True)
    parser.add_argument('--hazards', type=Path, default=Path('catalog/noaa-survey-hazards.json'))
    parser.add_argument('--mpas', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.context.resolve().is_relative_to(Path('var/review').resolve()):
        raise ValueError('Camera coordinates must remain in unpublished var/review')
    raw = args.context.read_bytes()
    result = audit(json.loads(raw), raw, json.loads(args.reconciliation.read_text()),
                   json.loads(args.enc.read_text()), json.loads(args.hazards.read_text()),
                   json.loads(args.mpas.read_text()), args.report.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, indent=2) + '\n')
    temp.replace(args.output)
    print(json.dumps({'survey_id': result['survey_id'],
        'camera_windows': result['original_qualified_historical_camera_windows'],
        'historical_danger_distance_m_range': result['minimum_historical_danger_distance_m_range'],
        'charted_danger_distance_m_range': result['minimum_charted_danger_distance_m_range']}))


if __name__ == '__main__':
    main()

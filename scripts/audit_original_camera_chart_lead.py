"""Compare one hash-pinned original NOAA BAG/camera lead with chart and MPA context.

This is a bounded historical habitat review, not a fishing target, safe route,
or proof of current fish. Charted seabed symbols can be generalized and old.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from scripts.audit_usgs_video_observations import open_original_zip
from scripts.build_usgs_statewide_context import mpa_union
from scripts.refresh_enc_hazards import BASE, fetch_json, query_layer

SERVICES = (('enc_harbour', 'Harbor'), ('enc_approach', 'Approach'), ('enc_coastal', 'Coastal'))


def audit(pair, camera_raw, enc, mpa_snapshot, report, report_raw):
    if pair['camera_archive_sha256'] != hashlib.sha256(camera_raw).hexdigest():
        raise ValueError('Original camera ZIP does not match the reviewed pair')
    if pair['survey_id'] != report['survey_id'] or pair['survey_report_url'] != report['report_url'] \
            or hashlib.sha256(report_raw).hexdigest() != report['report_sha256']:
        raise ValueError('Original descriptive report does not match the reviewed survey')
    if len(enc.get('query_receipts', [])) != 18 or enc.get('source_url') != BASE \
            or sum(r['count'] for r in enc['query_receipts']) != len(enc.get('features', [])):
        raise ValueError('Complete bounded ENC danger receipt required')
    bounds = enc['bounds']
    mpa = mpa_union(mpa_snapshot)
    zone = int((sum(bounds[::2]) / 2 + 180) // 6) + 1
    project = Transformer.from_crs('EPSG:4326', f'EPSG:326{zone:02d}', always_xy=True).transform
    mpa_projected = transform(project, mpa)
    reader = open_original_zip(camera_raw)
    charted_dangers = [transform(project, shape(f['geometry'])) for f in enc['features']]
    chart = []
    receipts = []
    seabed_areas = []
    area_receipts = []
    for service, prefix in SERVICES:
        metadata, metadata_sha = fetch_json(f'{BASE}/{service}/MapServer?f=pjson')
        matches = [r['id'] for r in metadata.get('layers', []) if r.get('name') == prefix + '.Seabed_Area_point']
        if len(matches) != 1:
            raise ValueError('Required charted seabed-point layer changed')
        features, receipt = query_layer(service, 'Seabed_Area_point', matches[0], bounds)
        chart.extend(features)
        receipts.append({**receipt, 'metadata_sha256': metadata_sha})
        area_ids = [r['id'] for r in metadata.get('layers', []) if r.get('name') == prefix + '.Seabed_Area']
        if len(area_ids) != 1:
            raise ValueError('Required charted seabed-area layer changed')
        areas, area_receipt = query_layer(service, 'Seabed_Area', area_ids[0], bounds)
        seabed_areas.extend(areas)
        area_receipts.append({**area_receipt, 'metadata_sha256': metadata_sha})
    rock = [transform(project, shape(f['geometry'])) for f in chart
            if str(f.get('properties', {}).get('NATSUR') or '').lower() == 'rock']
    if not rock:
        raise ValueError('No charted rock symbols in the reviewed bounded scope')
    rows = []
    for transect in pair['transects']:
        indices = transect['camera_record_indices']
        if len(indices) != transect['window_count'] or len(indices) != len(set(indices)):
            raise ValueError('Original camera record identities are incomplete')
        distances = []
        danger_distances = []
        closures = []
        for index in indices:
            location = reader.shape(index).points[0]
            if not (bounds[0] <= location[0] <= bounds[2] and bounds[1] <= location[1] <= bounds[3]):
                raise ValueError('ENC bounds omit a reviewed camera observation')
            item = reader.record(index).as_dict()
            if str(item.get('MAJOR_GEO') or '').lower() not in {'rock', 'boulder', 'cobble'}:
                raise ValueError('Reviewed rocky camera identity changed')
            point = transform(project, Point(location))
            distances.append(min(point.distance(g) for g in rock))
            if charted_dangers:
                danger_distances.append(min(point.distance(g) for g in charted_dangers))
            closures.append(point.distance(mpa_projected))
        rows.append({'date': transect['date'], 'line': transect['line'],
            'historical_rocky_camera_windows': len(indices),
            'historical_rockfish_positive_windows': transect['rockfish_positive_windows'],
            'bottom_classes': transect['bottom_classes'],
            'measured_depth_m_mllw_range': transect['depth_m_mllw_range'],
            'product_uncertainty_m_range': transect['product_uncertainty_m_range'],
            'camera_position_bounds': transect['camera_position_bounds'],
            'nearest_charted_rock_symbol_m_range': [round(min(distances), 1), round(max(distances), 1)],
            'nearest_charted_danger_m_min': round(min(danger_distances), 1) if danger_distances else None,
            'nearest_cdfw_mpa_boundary_m_min': round(min(closures), 1),
            'within_100m_mpa_review_buffer': sum(distance <= 100 for distance in closures)})
    return {'schema_version': 1, 'scope': 'original-camera-chart-mpa-source-lead',
        'reviewed_at': datetime.now(timezone.utc).isoformat(),
        'survey_id': pair['survey_id'], 'original_bag_url': pair['bag_url'],
        'original_bag_sha256': pair['bag_sha256'],
        'original_camera_url': pair['camera_archive_url'],
        'original_camera_sha256': pair['camera_archive_sha256'],
        'survey_report_url': report['report_url'], 'survey_report_sha256': report['report_sha256'],
        'survey_report_interpretation': report['interpretation'],
        'survey_fishing_promotion_hold': pair.get('survey_hold'),
        'enc_danger_receipt_checked_at': enc['checked_at'],
        'enc_danger_queried_layers': len(enc['query_receipts']),
        'enc_danger_features_in_bounded_scope': len(enc['features']),
        'charted_seabed_point_receipts': receipts,
        'charted_seabed_point_count_by_nature': dict(Counter(str(f['properties'].get('NATSUR') or 'unknown').lower() for f in chart)),
        'charted_seabed_area_receipts': area_receipts,
        'charted_seabed_area_count_by_nature': dict(Counter(str(f['properties'].get('NATSUR') or 'unknown').lower() for f in seabed_areas)),
        'cdfw_mpa_retrieved_at': mpa_snapshot['sources']['mpas']['data_retrieved_at'],
        'transects': rows, 'historical_camera_windows': sum(r['historical_rocky_camera_windows'] for r in rows),
        'fishing_target': False, 'exportable': False,
        'limitations': [
            'Charted seabed symbols and any charted seabed areas are generalized, dated source observations; a nearby symbol or area does not delineate the camera-observed patch.',
            'Selected ENC danger classes returning zero do not certify safe navigation or an approach route.',
            'Historical camera rockfish codes are observations, not catch rates or present fish presence.',
            'The MPA screen is a dated geometry snapshot; exact current local rules, access and protected-area boundaries remain separate gates.',
            'No fishing coordinate, rating, plan or export is approved by this source-lead review.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--survey-id', required=True)
    p.add_argument('--bag-url', required=True)
    p.add_argument('--cruise', help='Select a camera archive when one BAG has multiple reviewed cruises')
    p.add_argument('--pairs', type=Path, default=Path('dist/data/noaa-statewide-regular-camera-review.json'))
    p.add_argument('--hazards', type=Path, default=Path('catalog/noaa-survey-hazards.json'))
    p.add_argument('--enc', type=Path, required=True)
    p.add_argument('--mpas', type=Path, required=True)
    p.add_argument('--camera-cache', type=Path, default=Path('var/usgs-video-cache'))
    p.add_argument('--report-cache', type=Path, default=Path('var/noaa-report-cache'))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    pairs = json.loads(a.pairs.read_text())
    matches = [r for r in pairs['pair_reviews'] if r['survey_id'] == a.survey_id
               and r['bag_url'] == a.bag_url and (a.cruise is None or r['cruise'] == a.cruise)]
    reports = [r for r in json.loads(a.hazards.read_text())['surveys'] if r['survey_id'] == a.survey_id]
    if len(matches) != 1 or len(reports) != 1 or not matches[0]['transects']:
        raise ValueError('One reviewed original BAG/camera pair and report are required')
    pair, report = matches[0], reports[0]
    result = audit(pair, (a.camera_cache / (pair['cruise'] + '_video_observations.zip')).read_bytes(),
                   json.loads(a.enc.read_text()), json.loads(a.mpas.read_text()), report,
                   (a.report_cache / (a.survey_id + '.pdf')).read_bytes())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temp = a.output.with_suffix(a.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, indent=2) + '\n')
    temp.replace(a.output)
    print(json.dumps({'survey_id': result['survey_id'], 'historical_camera_windows': result['historical_camera_windows'],
                      'charted_seabed_point_count_by_nature': result['charted_seabed_point_count_by_nature'],
                      'bounded_charted_dangers': result['enc_danger_features_in_bounded_scope']}))


if __name__ == '__main__':
    main()

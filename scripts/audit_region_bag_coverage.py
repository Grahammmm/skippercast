"""Triage original NOAA BAG geographic envelopes against actual region bounds.

An intersecting envelope is a source lead, never proof of surveyed cells or reef.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from shapely.geometry import box


def build(audit, regions, holds):
    if audit.get('scope') != 'noaa-original-bag-native-overview-audit':
        raise ValueError('Wrong NOAA BAG audit')
    if holds.get('scope') != 'reviewed-noaa-survey-fishing-lead-holds':
        raise ValueError('Wrong NOAA hold registry')
    held = {item['survey_id']: item for item in holds['holds']}
    if len(held) != len(holds['holds']):
        raise ValueError('Duplicate NOAA hold')
    rows = []
    for region in regions:
        bounds = region['bounds']
        if len(bounds) != 4 or not bounds[0] < bounds[2] or not bounds[1] < bounds[3]:
            raise ValueError('Invalid region bounds')
        footprint = box(*bounds)
        leads = []
        for item in audit['files']:
            if item['status'] != 'ok':
                continue
            source_bounds = item['raster_bounds_wgs84']
            if not box(*source_bounds).intersects(footprint):
                continue
            hold = held.get(item['survey_id'])
            leads.append({
                'survey_id': item['survey_id'], 'bag_url': item['url'],
                'bag_sha256': item['file_sha256'], 'bag_bounds': source_bounds,
                'resolution_m': item['overview_resolution_m'],
                'fine_refinement_grids': item['refinement_grids_at_most_4m'],
                'metadata_status': item['metadata_status'],
                'survey_end': item['survey_end'],
                'fishing_promotion_hold': bool(hold),
                'hold_reason': hold['reason'] if hold else None,
            })
        leads.sort(key=lambda item: (item['survey_id'], item['bag_url']))
        rows.append({
            'region_id': region['id'], 'region_status': region['status'],
            'region_bounds': bounds, 'intersecting_bag_bboxes': len(leads),
            'held_bag_bboxes': sum(item['fishing_promotion_hold'] for item in leads),
            'unheld_fine_regular_bag_bboxes': sum(
                not item['fishing_promotion_hold'] and max(item['resolution_m']) <= 4
                and item['fine_refinement_grids'] == 0
                and item['metadata_status'] == 'mllw-product-uncertainty-reviewed-by-adapter'
                for item in leads),
            'leads': leads,
        })
    return {
        'schema_version': 1, 'scope': 'regional-noaa-bag-envelope-review',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'audit_collected_at': audit['collected_at'], 'max_audited_file_bytes': audit['max_bytes'],
        'method': 'Intersect each inspected original BAG raster envelope with the exact region bounds. A broad variable-resolution overview may intersect without any surveyed native cells inside.',
        'limitations': ['Not surveyed-area coverage, substrate, navigation, legal clearance, fish presence or a fishing spot.',
                        'Only original BAGs within the bounded audit are included; missing and larger files remain unassessed.'],
        'regions': rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=Path('var/noaa-native-audit-100mb-refined.json'))
    parser.add_argument('--regions', type=Path, default=Path('regions'))
    parser.add_argument('--holds', type=Path, default=Path('catalog/noaa-survey-lead-holds.json'))
    parser.add_argument('--output', type=Path, default=Path('dist/data/noaa-region-bag-envelope-review.json'))
    args = parser.parse_args()
    regions = [json.loads(path.read_text()) for path in sorted(args.regions.glob('*/region.json'))]
    packet = build(json.loads(args.audit.read_text()), regions, json.loads(args.holds.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, separators=(',', ':')) + '\n')
    print([(r['region_id'], r['intersecting_bag_bboxes'], r['unheld_fine_regular_bag_bboxes'])
           for r in packet['regions']])


if __name__ == '__main__':
    main()

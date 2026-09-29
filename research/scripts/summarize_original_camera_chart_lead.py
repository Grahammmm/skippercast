"""Publish a coordinate-free receipt for an original camera/BAG/chart review.

The full review stays under var/review. This summary is source evidence only;
it cannot become a target, score, navigation route or chartplotter export.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize(review: dict) -> dict:
    transects = review.get('transects')
    if (review.get('fishing_target') is not False
            or review.get('exportable') is not False
            or review.get('enc_danger_queried_layers') != 18
            or not review.get('survey_report_interpretation')
            or not review.get('survey_report_sha256')
            or not review.get('cdfw_mpa_retrieved_at')
            or not isinstance(transects, list) or not transects
            or sum(row['historical_rocky_camera_windows'] for row in transects)
               != review.get('historical_camera_windows')):
        raise ValueError('An exact, report-reviewed, complete research review is required')
    allowed = (
        'date', 'line', 'historical_rocky_camera_windows',
        'historical_rockfish_positive_windows', 'bottom_classes',
        'measured_depth_m_mllw_range', 'product_uncertainty_m_range',
        'nearest_charted_rock_symbol_m_range', 'nearest_charted_danger_m_min',
        'nearest_cdfw_mpa_boundary_m_min', 'within_100m_mpa_review_buffer',
    )
    rows = [{key: row[key] for key in allowed} for row in transects]
    result = {
        'schema_version': 1,
        'scope': 'original-camera-bag-chart-research-summary',
        'survey_id': review['survey_id'],
        'reviewed_at': review['reviewed_at'],
        'original_bag_url': review['original_bag_url'],
        'original_bag_sha256': review['original_bag_sha256'],
        'original_camera_url': review['original_camera_url'],
        'original_camera_sha256': review['original_camera_sha256'],
        'survey_report_url': review['survey_report_url'],
        'survey_report_sha256': review['survey_report_sha256'],
        'survey_report_interpretation': review['survey_report_interpretation'],
        'survey_fishing_promotion_hold': review['survey_fishing_promotion_hold'],
        'enc_danger_receipt_checked_at': review['enc_danger_receipt_checked_at'],
        'enc_danger_queried_layers': review['enc_danger_queried_layers'],
        'enc_danger_features_in_bounded_scope': review['enc_danger_features_in_bounded_scope'],
        'charted_seabed_point_count_by_nature': review['charted_seabed_point_count_by_nature'],
        'charted_seabed_area_count_by_nature': review['charted_seabed_area_count_by_nature'],
        'cdfw_mpa_retrieved_at': review['cdfw_mpa_retrieved_at'],
        'historical_camera_windows': review['historical_camera_windows'],
        'transects': rows,
        'fishing_target': False,
        'exportable': False,
        'next_checks': [
            'Reconcile original HCell seabed and rock features with the current ENC; review every charted hazard and route.',
            'Compare exact source habitat polygons and survey gaps with original BAG native cells and camera position uncertainty.',
            'Refresh complete CDFW MPAs and federal restrictions, then verify the exact site, method and date under local rules.',
            'Review approach route, harbor entrance and current conditions before any fishing-plan promotion.',
        ],
        'limitations': review['limitations'],
    }
    encoded = json.dumps(result)
    if any(key in encoded for key in ('camera_position_bounds', '"latitude"', '"longitude"')):
        raise ValueError('Research summary leaked a coordinate field')
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    if not a.review.resolve().is_relative_to(Path('var/review').resolve()):
        raise ValueError('Full source review must remain under var/review')
    result = summarize(json.loads(a.review.read_text()))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = a.output.with_suffix(a.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(a.output)
    print(json.dumps({'survey_id': result['survey_id'],
                      'historical_camera_windows': result['historical_camera_windows'],
                      'transects': len(result['transects']),
                      'fishing_target': result['fishing_target']}))


if __name__ == '__main__':
    main()

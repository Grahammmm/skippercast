"""Publish a coordinate-free receipt for an original camera/BAG/chart review.

The full review stays under var/review. This summary is source evidence only;
it cannot become a target, score, navigation route or chartplotter export.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path
import re


CAMERA_LIMITATIONS = (
    'Charted seabed symbols and any charted seabed areas are generalized, dated source observations; a nearby symbol or area does not delineate the camera-observed patch.',
    'Selected ENC danger classes returning zero do not certify safe navigation or an approach route.',
    'Historical camera rockfish codes are observations, not catch rates or present fish presence.',
    'The MPA screen is a dated geometry snapshot; exact current local rules, access and protected-area boundaries remain separate gates.',
    'No fishing coordinate, rating, plan or export is approved by this source-lead review.',
)
BOTTOM_CLASSES = {'rock', 'boulder', 'cobble'}
# S-57 NATSUR labels from the ENC seabed layers, including comma-separated combinations.
ENC_NATURES = {'mud', 'clay', 'silt', 'sand', 'stone', 'gravel', 'pebbles',
               'cobbles', 'rock', 'lava', 'coral', 'shells', 'boulder', 'unknown'}


# Both summary writers use these validators at the private JSON boundary.
def count(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f'{field}: expected a nonnegative integer count')
    return value


def measurement(value, field):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError(f'{field}: expected a finite measurement')
    return value


def _matching_text(value, field, pattern):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f'{field}: invalid source review field')
    return value


def public_id(value, field):
    return _matching_text(value, field, r'[A-Za-z0-9][A-Za-z0-9_.-]*')


def iso_date(value, field):
    _matching_text(value, field, r'\d{4}-\d{2}-\d{2}')
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{field}: expected an ISO date') from None
    return value


def timestamp(value, field):
    try:
        if isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None:
            return value
    except ValueError:
        pass
    raise ValueError(f'{field}: expected a timezone-qualified ISO timestamp')


def source_url(value, field):
    # Source-credit links have no credentials, query parameters or fragments.
    return _matching_text(value, field, r'https://[A-Za-z0-9.-]+/[A-Za-z0-9._~/%+-]+')


def sha256(value, field):
    return _matching_text(value, field, r'[a-fA-F0-9]{64}')


def pair(value, field, validate):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f'{field}: expected a pair')
    return [validate(item, field) for item in value]


def project(row, fields):
    if not isinstance(row, dict):
        raise ValueError('Expected a review object')
    result = {}
    for field, validate in fields.items():
        if field not in row:
            raise ValueError(f'{field}: required review evidence is missing')
        result[field] = validate(row[field], field)
    return result


def _range(value, field):
    lo, hi = pair(value, field, measurement)
    if lo > hi:
        raise ValueError(f'{field}: expected an ordered range')
    return [lo, hi]


def _class_counts(value, field):
    if not isinstance(value, dict):
        raise ValueError(f'{field}: expected seabed class counts')
    result = {}
    for label, total in value.items():
        if not isinstance(label, str) or (
            label not in BOTTOM_CLASSES if field == 'bottom_classes'
            else any(part.strip() not in ENC_NATURES for part in label.split(','))
        ):
            raise ValueError(f'{field}: expected reviewed seabed class labels')
        result[label] = count(total, field)
    return result


def _source_text(value, field):
    # Interpretation and hold come from the upstream reviewed survey/report pair.
    if not isinstance(value, str) or not value.strip() or not value.isprintable() or any(c in value for c in '{}[]'):
        raise ValueError(f'{field}: expected source review text')
    return value


def _limitations(value):
    if not isinstance(value, list) or not value or any(item not in CAMERA_LIMITATIONS for item in value):
        raise ValueError('limitations: expected reviewed camera limitations')
    return [CAMERA_LIMITATIONS[CAMERA_LIMITATIONS.index(item)] for item in value]


def summarize(review: dict) -> dict:
    if not isinstance(review, dict):
        raise ValueError('Expected a camera review object')
    transects = review.get('transects')
    if (review.get('fishing_target') is not False
            or review.get('exportable') is not False
            or type(review.get('enc_danger_queried_layers')) is not int
            or review['enc_danger_queried_layers'] != 18
            or not review.get('survey_report_interpretation')
            or not review.get('survey_report_sha256')
            or not review.get('cdfw_mpa_retrieved_at')
            or not isinstance(transects, list) or not transects):
        raise ValueError('An exact, report-reviewed, complete research review is required')
    rows = [project(row, {
        'date': iso_date, 'line': public_id,
        'historical_rocky_camera_windows': count,
        'historical_rockfish_positive_windows': lambda v, f: None if v is None else count(v, f),
        'bottom_classes': _class_counts,
        'measured_depth_m_mllw_range': _range, 'product_uncertainty_m_range': _range,
        'nearest_charted_rock_symbol_m_range': _range,
        'nearest_charted_danger_m_min': lambda v, f: None if v is None else measurement(v, f),
        'nearest_cdfw_mpa_boundary_m_min': measurement, 'within_100m_mpa_review_buffer': count,
    }) for row in transects]
    total = count(review.get('historical_camera_windows'), 'historical_camera_windows')
    if sum(row['historical_rocky_camera_windows'] for row in rows) != total:
        raise ValueError('An exact, report-reviewed, complete research review is required')
    result = {
        'schema_version': 1,
        'scope': 'original-camera-bag-chart-research-summary',
        **project(review, {
            'survey_id': public_id, 'reviewed_at': timestamp,
            'original_bag_url': source_url, 'original_bag_sha256': sha256,
            'original_camera_url': source_url, 'original_camera_sha256': sha256,
            'survey_report_url': source_url, 'survey_report_sha256': sha256,
            'survey_report_interpretation': _source_text,
            'survey_fishing_promotion_hold': lambda v, f: None if v is None else _source_text(v, f),
            'enc_danger_receipt_checked_at': timestamp, 'enc_danger_queried_layers': count,
            'enc_danger_features_in_bounded_scope': count,
            'charted_seabed_point_count_by_nature': _class_counts,
            'charted_seabed_area_count_by_nature': _class_counts,
            'cdfw_mpa_retrieved_at': timestamp,
        }),
        'historical_camera_windows': total,
        'transects': rows,
        'fishing_target': False,
        'exportable': False,
        'next_checks': [
            'Reconcile original HCell seabed and rock features with the current ENC; review every charted hazard and route.',
            'Compare exact source habitat polygons and survey gaps with original BAG native cells and camera position uncertainty.',
            'Refresh complete CDFW MPAs and federal restrictions, then verify the exact site, method and date under local rules.',
            'Review approach route, harbor entrance and current conditions before any fishing-plan promotion.',
        ],
        'limitations': _limitations(review.get('limitations')),
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

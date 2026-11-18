"""F33-03: offline controls for coordinate-free research summaries.

Run ``python -B -m pytest -q tests/unit/test_f33_03_audit.py`` for both
controls. The module CLI also reports the two original malformed cases.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from research.scripts.summarize_native_hard_reviews import summarize as summarize_native
from research.scripts.summarize_original_camera_chart_lead import summarize as summarize_camera


STAMP = '2000-01-02T00:00:00Z'
SURVEY = 'SYNTHETIC-REVIEW'
REPORT = 'https://example.invalid/report.pdf'
LIMITATION = 'Historical camera rockfish codes are observations, not catch rates or present fish presence.'
NATIVE_LIMITATION = 'Historical review components are not fishing waypoints, verified fish habitat, or safe navigation areas.'
HOLD = 'Synthetic survey remains held for fishing promotion.'


def _geometry():
    # A geometry marker with no position, even a fictional one.
    return {'type': 'GeometryCollection', 'geometries': []}


def _camera_review():
    return {
        'survey_id': SURVEY, 'reviewed_at': STAMP,
        'original_bag_url': 'https://example.invalid/original.bag', 'original_bag_sha256': 'a' * 64,
        'original_camera_url': 'https://example.invalid/camera.zip', 'original_camera_sha256': 'b' * 64,
        'survey_report_url': REPORT, 'survey_report_sha256': 'c' * 64,
        'survey_report_interpretation': 'Historical source observations only.',
        'survey_fishing_promotion_hold': HOLD,
        'enc_danger_receipt_checked_at': STAMP, 'enc_danger_queried_layers': 18,
        'enc_danger_features_in_bounded_scope': 0,
        'charted_seabed_point_count_by_nature': {'rock': 2},
        'charted_seabed_area_count_by_nature': {}, 'cdfw_mpa_retrieved_at': STAMP,
        'historical_camera_windows': 2, 'fishing_target': False, 'exportable': False,
        'limitations': [LIMITATION],
        'transects': [{
            'date': '2000-01-01', 'line': 'synthetic-line', 'bottom_classes': {'rock': 2},
            'historical_rocky_camera_windows': 2, 'historical_rockfish_positive_windows': 1,
            'measured_depth_m_mllw_range': [20.0, 21.0], 'product_uncertainty_m_range': [0.1, 0.2],
            'nearest_charted_rock_symbol_m_range': [8.0, 9.0], 'nearest_charted_danger_m_min': None,
            'nearest_cdfw_mpa_boundary_m_min': 180.0, 'within_100m_mpa_review_buffer': 0,
        }],
    }


def _native_review():
    return {
        'scope': 'native-noaa-usgs-hard-bottom-review', 'survey_id': SURVEY,
        'survey_dates': ['2000-01-01T03:04:05', '2000-01-02T06:07:08'], 'compiled_at': STAMP,
        'noaa_bag_url': 'https://example.invalid/native.bag', 'noaa_bag_sha256': 'd' * 64,
        'survey_report_url': REPORT, 'survey_report_sha256': 'c' * 64,
        'usgs_sources': [{
            'block_id': 'synthetic-block', 'archive_url': 'https://example.invalid/classes.zip',
            'archive_sha256': 'e' * 64, 'metadata_url': 'https://example.invalid/classes.xml',
            'metadata_sha256': 'f' * 64, 'original_resolution_m': [2.0, 2.0],
        }],
        'cdfw_mpa_retrieved_at': STAMP, 'noaa_federal_areas_retrieved_at': STAMP,
        'native_resolution_m': [2.0, 2.0], 'maximum_planning_depth_ft': 200,
        'bag_tracking_history': {
            'original_values_before_manual_edits': 1, 'depth_values_changed_in_current_grid': 1,
            'maximum_depth_revision_m': 0.2,
        },
        'counts': {
            'retained_components': 1, 'hard_cells_after_inset': 900,
            'depth_uncertainty_qualified_cells': 850,
            'hard_depth_cells_after_mpa_gea_historical_hazard_screen': 700,
        },
        'features': [{'type': 'Feature', 'geometry': _geometry(), 'properties': {
            'area_m2': 2800, 'fishing_target': False, 'exportable': False, 'legal_clearance': False,
        }}],
    }


def _native_summary(tmp_path, review):
    path = tmp_path / 'synthetic-native-review.json'
    path.write_text(json.dumps(review), encoding='utf-8')
    return summarize_native([path])


def _geometry_path(value, path='$'):
    if isinstance(value, dict):
        if value.get('type') == 'GeometryCollection':
            return path
        for key, item in value.items():
            if key in {'geometry', 'coordinates'}:
                return f'{path}.{key}'
            if found := _geometry_path(item, f'{path}.{key}'):
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if found := _geometry_path(item, f'{path}[{index}]'):
                return found
    return None


def _assert_camera(summary):
    assert summary['survey_id'] == SURVEY
    assert summary['historical_camera_windows'] == 2
    assert summary['transects'][0]['line'] == 'synthetic-line'
    assert summary['transects'][0]['bottom_classes'] == {'rock': 2}
    assert summary['charted_seabed_point_count_by_nature'] == {'rock': 2}
    assert summary['transects'][0]['measured_depth_m_mllw_range'] == [20.0, 21.0]
    assert (summary['survey_report_url'], summary['survey_report_sha256']) == (REPORT, 'c' * 64)
    assert summary['survey_report_interpretation'] == 'Historical source observations only.'
    assert summary['survey_fishing_promotion_hold'] == HOLD
    assert summary['limitations'] == [LIMITATION]
    assert summary['fishing_target'] is summary['exportable'] is False


def _assert_native(summary):
    survey, = summary['surveys']
    assert survey['survey_id'] == SURVEY
    assert survey['survey_dates'] == _native_review()['survey_dates']
    assert survey['counts'] == _native_review()['counts']
    assert survey['retained_component_area_m2'] == 2800
    assert survey['bag_tracking_history'] == _native_review()['bag_tracking_history']
    assert survey['usgs_sources'] == _native_review()['usgs_sources']
    assert (survey['survey_report_url'], survey['survey_report_sha256']) == (REPORT, 'c' * 64)
    assert survey['fishing_target'] is survey['exportable'] is survey['legal_clearance'] is False
    assert NATIVE_LIMITATION in summary['limitations']


def test_camera_valid_aggregate_keeps_evidence_and_hold():
    # A blanket rejection or empty projection would hide the leak but lose evidence.
    summary = summarize_camera(_camera_review())
    assert _geometry_path(summary) is None
    _assert_camera(summary)


def test_native_valid_aggregate_keeps_evidence_and_omits_features(tmp_path):
    # The legitimate private feature contributes only aggregate area and count.
    summary = _native_summary(tmp_path, _native_review())
    assert _geometry_path(summary) is None
    _assert_native(summary)


def test_camera_limitations_only_use_reviewed_text():
    # An otherwise valid review cannot pass through objects or unreviewed prose.
    for extra in (_geometry(), 'An arbitrary private comment.'):
        camera = _camera_review()
        camera['limitations'].append(extra)
        assert _check_affected('camera', lambda: summarize_camera(camera), _assert_camera) == 0


@pytest.mark.parametrize('field,value', [
    ('line', _geometry()),
    ('bottom_classes', {'rock': _geometry()}),
    ('product_uncertainty_m_range', [0.1, _geometry()]),
    ('measured_depth_m_mllw_range', [21.0, 20.0]),
    ('nearest_charted_danger_m_min', float('nan')),
    ('within_100m_mpa_review_buffer', True),
])
def test_camera_rejects_misbound_transect_values(field, value):
    # Merely selecting the transect's keys still accepts bad values under those keys.
    review = _camera_review()
    review['transects'][0][field] = value
    with pytest.raises(ValueError, match=field):
        summarize_camera(review)


@pytest.mark.parametrize('container', ['counts', 'bag_tracking_history', 'usgs_sources'])
def test_native_projects_only_known_nested_fields(tmp_path, container):
    # Whole-object copies reintroduce private data even when known fields are valid.
    review = _native_review()
    obj = review[container][0] if container == 'usgs_sources' else review[container]
    obj['geometry'] = _geometry()
    assert _check_affected(container, lambda: _native_summary(tmp_path, review), _assert_native) == 0


@pytest.mark.parametrize('container,field,value', [
    ('counts', 'retained_components', True),
    ('bag_tracking_history', 'maximum_depth_revision_m', _geometry()),
    ('usgs_sources', 'original_resolution_m', [_geometry(), 2]),
    ('usgs_sources', 'archive_sha256', 'not-a-digest'),
])
def test_native_rejects_bad_values_in_known_fields(tmp_path, container, field, value):
    # Selecting keys alone could still leak their nested values or bless bad provenance.
    review = _native_review()
    obj = review[container][0] if container == 'usgs_sources' else review[container]
    obj[field] = value
    with pytest.raises(ValueError, match=field):
        _native_summary(tmp_path, review)


def _check_affected(label, summarize, check_evidence):
    try:
        summary = summarize()
    except ValueError:
        print(f'{label}: PASS (malformed review rejected)')
        return 0
    if path := _geometry_path(summary):
        print(f'{label}: GAP (nested geometry returned at {path})')
        return 1
    check_evidence(summary)
    print(f'{label}: PASS (geometry omitted; valid evidence retained)')
    return 0


if __name__ == '__main__':
    camera = _camera_review()
    camera['limitations'].append(_geometry())
    native = _native_review()
    native['counts']['geometry'] = _geometry()
    with TemporaryDirectory(prefix='f33-03-') as work:
        camera_gap = _check_affected('camera', lambda: summarize_camera(camera), _assert_camera)
        native_gap = _check_affected('native', lambda: _native_summary(Path(work), native), _assert_native)
    raise SystemExit(max(camera_gap, native_gap))

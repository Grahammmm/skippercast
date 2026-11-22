"""Contract tests at the saved water-stage receipt/audit boundary (no GIS)."""

import hashlib
import json

import pytest

from scripts.relief.north_water_evidence import summarize
from skippercast.relief import receipts

_REGION = 'shelter-cove-north-mendocino'


@pytest.fixture
def saved_water(tmp_path):
    def save(*, omit=None, unavailable=None):
        audit = {
            'region': _REGION,
            'region_bounds_wgs84': [-125, 39, -124, 40],
            'frame_wgs84': [-125, 39, -124, 40],
            'close_m': 36.0,
            'connect_m': 250.0,
            'hor_acc_values_m': [4.31, 18.0, 36.0],
            'unavailable_tiles': ['10/156/388'] if unavailable is None else unavailable,
            'report': {
                'cut_arcs': [{'from_lon_lat': [-124.6, 39.6], 'to_lon_lat': [-124.59, 39.6],
                              'mid_lon_lat': [-124.595, 39.6], 'length_m': 860.0}],
                'components_dropped': [],
                'displacement_bound_m': 72.0,
                'max_displacement_m': 80.0,
                'unlisted_beyond_bound': [],
            },
            'inputs': {'manifest_sha256': 'b' * 64,
                       'tiles': [{'tile': '10/157/388', 'sha256': 'a' * 64}]},
        }
        if omit:
            del audit[omit]
        path = tmp_path / _REGION / 'water/water.json'
        path.parent.mkdir(parents=True)
        raw = receipts.canonical(audit) + b'\n'
        path.write_bytes(raw)
        params = {'close_m': 'max stated HOR_ACC', 'connect_m': 250.0}
        inputs = [{'path': 'manifest.json', 'role': 'shoreline-manifest', 'sha256': 'b' * 64}]
        code = {'repo_sha': 'c' * 40, 'stage_digest': 'd' * 64}
        receipt = {
            'schema': 'sc-stage-receipt/1', 'region': _REGION, 'stage': 'water', 'scope': None,
            'generation': receipts.generation(inputs, [], code['stage_digest'], params),
            'params': params, 'inputs': inputs, 'upstream': [], 'code': code, 'target': 'water',
            'outputs': [
                # The polygon need not be present: the summary verifies only the audit leaf.
                {'path': 'water/water.geojson', 'bytes': 300, 'sha256': 'f' * 64},
                {'path': 'water/water.json', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()},
            ],
            'rc': 0, 'status': 'ok', 'attempt': 1, 'held_reason': None, 'error': None,
            'metrics': {'close_m': 36.0, 'connect_m': 250.0},
        }
        receipts.write_json_atomic(tmp_path / _REGION / 'stages/water.json', receipt)
        return path

    return save


@pytest.mark.parametrize('unavailable', [['10/156/388'], []], ids=['recorded-tile', 'recorded-empty'])
def test_reads_saved_values_without_rejudging_displacement(tmp_path, saved_water, unavailable):
    """Use persisted values, not default radii or a max-displacement veto that ignores listed cuts."""
    saved_water(unavailable=unavailable)
    assert summarize(tmp_path, _REGION) == {
        'status': 'verified', 'region': _REGION, 'max_stated_accuracy_m': 36.0,
        'close_m': 36.0, 'unavailable_tiles': unavailable,
    }


def test_refuses_same_size_changed_audit(tmp_path, saved_water):
    """A valid, same-size edit defeats a file size or JSON-only check, but not the raw digest."""
    path = saved_water()
    raw = path.read_bytes()
    changed = raw.replace(b'10/156/388', b'10/156/389')
    assert len(changed) == len(raw) and changed != raw
    assert json.loads(changed)['unavailable_tiles'] == ['10/156/389']
    path.write_bytes(changed)
    result = summarize(tmp_path, _REGION)
    assert result['status'] == 'incomplete'
    assert 'digest' in result['reason']
    assert 'unavailable_tiles' not in result and 'close_m' not in result


@pytest.mark.parametrize(('missing', 'output_key'), [
    ('close_m', 'close_m'),
    ('hor_acc_values_m', 'max_stated_accuracy_m'),
    ('unavailable_tiles', 'unavailable_tiles'),
])
def test_reports_missing_fields_without_substitution(tmp_path, saved_water, missing, output_key):
    """Don't backfill from duplicated metrics, another audit field, or an assumed empty list."""
    saved_water(omit=missing)
    result = summarize(tmp_path, _REGION)
    assert result['status'] == 'incomplete'
    assert result['missing_or_invalid'] == [missing]
    assert output_key not in result
    present = {'max_stated_accuracy_m': 36.0, 'close_m': 36.0, 'unavailable_tiles': ['10/156/388']}
    del present[output_key]
    assert {key: result[key] for key in present} == present

"""A listed-but-malformed rough-first reference refuses; only true absence is control mode."""
import json

import pytest

from skippercast.seafloor import rough_first
from skippercast.seafloor.rough_first import REFERENCE_FILE, load_reference

VALID = {
    'rough_zoom_bytes': {'8': 100, '9': 200, '10': 300, '11': 400},
    'opening_view': {'tiles': ['9/80/200'], 'bytes': 50},
    'margin_per_mille': 100,
    'anomaly_floor': 0.5,
    'occurrence_floor': 0.5,
}


def write(tmp_path, document):
    path = tmp_path/REFERENCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))


def test_listed_null_reference_refuses(tmp_path):
    write(tmp_path, {'regions': {'synthetic-region': None}})
    with pytest.raises(ValueError, match='Invalid rough-first reference'):
        load_reference(tmp_path, 'synthetic-region')


@pytest.mark.parametrize('entry', [False, 0, 'text', []])
def test_listed_nonobject_reference_refuses(tmp_path, entry):
    write(tmp_path, {'regions': {'synthetic-region': entry}})
    with pytest.raises(ValueError, match='Invalid rough-first reference'):
        load_reference(tmp_path, 'synthetic-region')


@pytest.mark.parametrize('document', [
    [], 'text', None, {'regions': None}, {'regions': []}, {'regions': 'x'}, {'regions': 0}])
def test_malformed_reference_containers_refuse(tmp_path, document):
    write(tmp_path, document)
    with pytest.raises(ValueError, match='Invalid rough-first reference'):
        load_reference(tmp_path, 'synthetic-region')


def test_missing_file_and_absent_region_controls(tmp_path):
    assert load_reference(tmp_path, 'synthetic-region') is None
    write(tmp_path, {})
    assert load_reference(tmp_path, 'synthetic-region') is None
    write(tmp_path, {'regions': {}})
    assert load_reference(tmp_path, 'synthetic-region') is None
    write(tmp_path, {'regions': {'other-region': VALID}})
    assert load_reference(tmp_path, 'synthetic-region') is None


def test_valid_synthetic_reference_is_unchanged(tmp_path):
    write(tmp_path, {'regions': {'synthetic-region': VALID}})
    assert load_reference(tmp_path, 'synthetic-region') == VALID
    write(tmp_path, {'regions': {'synthetic-region': {}}})
    with pytest.raises(ValueError, match='Invalid rough-first reference'):
        load_reference(tmp_path, 'synthetic-region')

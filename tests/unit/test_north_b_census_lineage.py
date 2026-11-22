"""Synthetic review inputs; the operational binder and selector are not run."""

import hashlib
import json

import pytest

from scripts.relief.north_b_census_lineage import main

NATIVE_CENSUS = b'{\r\n "source_id": "fixture-native", "files": [{"path": "native-a.tif"}]\r\n}\r\n'


@pytest.fixture
def inputs(tmp_path):
    census_path = tmp_path / 'native.json'
    census_path.write_bytes(NATIVE_CENSUS)
    pair = {'source_id': 'fixture-native', 'source_sha256': hashlib.sha256(NATIVE_CENSUS).hexdigest()}
    proposed = {
        'fort-bragg-point-arena': dict(pair),
        'shelter-cove-north-mendocino': dict(pair),
        'humboldt-bay-cape-mendocino': dict(pair),
    }
    return census_path, tmp_path / 'proposed.json', proposed


def run_review(inputs):
    census_path, proposed_path, proposed = inputs
    proposed_path.write_text(json.dumps(proposed), encoding='utf-8')
    return main([str(census_path), str(proposed_path)])


def test_accepts_the_shared_native_pair_for_all_three_regions(inputs, capsys):
    # Hashing reserialized JSON rather than the supplied bytes rejects this valid pin.
    assert run_review(inputs) == 0
    assert json.loads(capsys.readouterr().out) == inputs[2]


@pytest.mark.parametrize('field, replacement, diagnostic', [
    pytest.param('source_sha256', hashlib.sha256(NATIVE_CENSUS.replace(b'native-a', b'native-b')).hexdigest(),
                 'SHA-256 mismatch', id='same-source-id-different-revision'),
    pytest.param('source_id', 'fixture-other-native', 'source_id mismatch', id='same-digest-different-source-id'),
])
def test_rejects_a_proposal_matching_only_half_the_pair(inputs, capsys, field, replacement, diagnostic):
    # An ID-only join accepts the wrong revision; a digest-only join accepts the wrong source ID.
    region = 'humboldt-bay-cape-mendocino'
    inputs[2][region][field] = replacement
    assert run_review(inputs) == 1
    output = capsys.readouterr()
    assert not output.out
    assert region in output.err and diagnostic in output.err


def test_rejects_a_missing_region_even_if_the_supplied_pairs_match(inputs, capsys):
    # Iterating only over supplied proposals would accept a two-region review.
    inputs[2].pop('shelter-cove-north-mendocino')
    assert run_review(inputs) == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'exactly the three North B regions' in output.err

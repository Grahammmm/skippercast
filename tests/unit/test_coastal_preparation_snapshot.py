"""Ordered-trial preparations are detached from caller-owned byte descriptors."""
import copy
import json

import pytest

from skippercast.coastal.coordinator.authenticated import INPUT_CONTRACT
from skippercast.coastal.coordinator.ordered_trial import WINDOWS, prepare
from tests.unit.test_coastal_window_side import (
    GRANT_CONTRACT, _grant, _packet, _windows, _write_metadata)


def _inputs(root, side, windows):
    grant_ref = _write_metadata(root, 'grant.json', _grant(side, windows), GRANT_CONTRACT)
    request_refs = [
        _write_metadata(root, 'packet-%d.json' % i, _packet(side, w), INPUT_CONTRACT)
        for i, w in enumerate(windows)
    ]
    return grant_ref, request_refs


def _prepare(root, grant_ref, request_refs):
    return prepare(str(root), grant_ref, request_refs, start_epoch=0.0,
                   deadline_epoch=3600.0, cumulative_limit_bytes=200000,
                   prior_effective_bytes=0)


def _bytes(value):
    return json.dumps(value, sort_keys=True)


@pytest.mark.parametrize('side,windows', [(32, WINDOWS), (64, None)])
def test_caller_mutation_does_not_rewrite_preparation(side, windows, tmp_path):
    windows = windows or _windows(side)
    root = tmp_path / 'root'
    root.mkdir()
    grant_ref, request_refs = _inputs(root, side, windows)
    prepared = _prepare(root, grant_ref, request_refs)
    before = _bytes(prepared)
    grant_ref['sha256'] = '0' * 64
    grant_ref['path'] = 'elsewhere.json'
    request_refs[0]['sha256'] = '1' * 64
    request_refs.reverse()
    request_refs.append({'path': 'extra'})
    assert _bytes(prepared) == before
    request_refs.clear()
    assert len(prepared['requests']) == 4


def test_returned_descriptors_do_not_mutate_inputs(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    grant_ref, request_refs = _inputs(root, 32, WINDOWS)
    controls = copy.deepcopy((grant_ref, request_refs))
    prepared = _prepare(root, grant_ref, request_refs)
    assert prepared['grant'] == grant_ref and prepared['requests'] == request_refs
    prepared['grant']['sha256'] = 'x'
    for row in prepared['requests']:
        row['sha256'] = 'x'
    prepared['requests'].append({})
    assert (grant_ref, request_refs) == controls


def test_repeated_preparations_are_independent(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    grant_ref, request_refs = _inputs(root, 32, WINDOWS)
    first = _prepare(root, grant_ref, request_refs)
    second = _prepare(root, grant_ref, request_refs)
    assert first == second
    first['grant']['sha256'] = 'x'
    first['requests'][0]['sha256'] = 'x'
    assert second['grant'] == grant_ref
    assert second['requests'] == request_refs

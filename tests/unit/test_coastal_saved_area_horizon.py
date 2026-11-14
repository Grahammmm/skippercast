"""validate_adoption refuses unrepresentable or invalid clocks locally, before any metadata or database access.

Boundary: the real continuation_grant and clock guard run; metadata_document is replaced by a
sentinel and resolve/sqlite3 by no-call spies, so nothing is opened.
"""
import copy
import math

import pytest

from skippercast.coastal.coordinator import saved_area

REFUSAL = 'finite prospective adoption horizon required'
HUGE = 10 ** 400


class Reached(Exception):
    pass


def _grant(contract=saved_area.CONTRACT):
    return dict(saved_area_continuation_contract=contract, window_count=4, window_side=128,
                source_reuse_contract=None, larger_runtime_contract='coastal-managed-eight-copy-four128-v1',
                source=dict(bytes=36757568), source_volume_cap_bytes=220545408,
                prior_effective_bytes=895006524, cumulative_limit_bytes=1115551932,
                execution_authorized=True, window_set=[1], source_root='s', source_relative_path='r',
                output_root='new-out')


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def metadata(*args):
        seen.append('metadata')
        raise Reached

    def spy(name):
        def fail(*args, **kwargs):
            seen.append(name)
            raise AssertionError(name + ' must not be called')
        return fail

    monkeypatch.setattr(saved_area, 'metadata_document', metadata)
    monkeypatch.setattr(saved_area, 'resolve', spy('resolve'))
    monkeypatch.setattr(saved_area, 'load', spy('load'))
    monkeypatch.setattr(saved_area.sqlite3, 'connect', spy('sqlite3.connect'))
    return seen


def _run(tmp_path, now, horizon, grant=None):
    root = tmp_path / 'root'
    root.mkdir(exist_ok=True)
    grant = _grant() if grant is None else grant
    before = copy.deepcopy(grant)
    try:
        saved_area.validate_adoption(root, {}, grant, now=now, horizon=horizon)
    finally:
        assert grant == before
        assert list(root.iterdir()) == [] and list(tmp_path.iterdir()) == [root]


@pytest.mark.parametrize('now,horizon', [
    (HUGE, 100), (100, HUGE), (-HUGE, 100), (100, -HUGE), (HUGE, HUGE), (-HUGE, -HUGE),
    (HUGE, 1.5), (1.5, HUGE), (-HUGE, 1.5),
])
def test_unrepresentable_integer_arguments_refuse_locally(tmp_path, calls, now, horizon):
    with pytest.raises(ValueError) as failure:
        _run(tmp_path, now, horizon)
    assert str(failure.value) == REFUSAL
    assert calls == []


@pytest.mark.parametrize('now,horizon', [
    (True, 100), (100, True), (None, 100), (100, None), ('100', 200), (100, '200'),
    ([100], 200), (100, {'a': 1}), (100, (200,)),
])
def test_wrong_types_and_booleans_stay_refused(tmp_path, calls, now, horizon):
    with pytest.raises(ValueError) as failure:
        _run(tmp_path, now, horizon)
    assert str(failure.value) == REFUSAL
    assert calls == []


@pytest.mark.parametrize('now,horizon', [
    (math.nan, 100.0), (100.0, math.nan), (math.inf, math.inf), (100.0, math.inf),
    (-math.inf, 100.0), (1e308, 1e308), (-1e308, -1e308),
])
def test_nonfinite_and_sum_overflow_remain_refused(tmp_path, calls, now, horizon):
    with pytest.raises(ValueError) as failure:
        _run(tmp_path, now, horizon)
    assert str(failure.value) == REFUSAL
    assert calls == []


@pytest.mark.parametrize('now,horizon', [(200, 100), (100, 3701), (100.0, 3700.5), (0, -1)])
def test_reversed_and_overlong_horizons_refuse(tmp_path, calls, now, horizon):
    with pytest.raises(ValueError) as failure:
        _run(tmp_path, now, horizon)
    assert str(failure.value) == REFUSAL
    assert calls == []


@pytest.mark.parametrize('now,horizon', [
    (100, 200), (100, 100), (100, 3700), (100.5, 200.25), (100, 3700.0), (0, 3600), (-50, -50),
])
def test_inclusive_horizon_and_numeric_types_preserved(tmp_path, calls, now, horizon):
    with pytest.raises(Reached):
        _run(tmp_path, now, horizon)
    assert calls == ['metadata']


def test_continuation_authority_precedes_clock_check(tmp_path, calls):
    for now, horizon in ((HUGE, 100), (100, -HUGE), (True, None)):
        with pytest.raises(ValueError, match='explicit saved-area continuation contract required'):
            _run(tmp_path, now, horizon, _grant('wrong-contract'))
    assert calls == []

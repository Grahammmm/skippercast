import json
from pathlib import Path

import pytest

from skippercast.coastal import child_release as cr
from tests.unit.child_release_fixture import fixture

MESSAGE = "finite non-boolean clock required"
HUGE = 10 ** 400
ROLES = ("render", "browser")
BOUNDS = ("start_epoch", "deadline_epoch", "start_monotonic", "deadline_monotonic")


@pytest.fixture(autouse=True)
def frozen_clocks(monkeypatch):
    monkeypatch.setattr(cr.time, "time", lambda: 1_800_000_000.0)
    monkeypatch.setattr(cr.time, "monotonic", lambda: 50_000.0)


def _snapshot(root):
    return {str(p): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def _run(ctx, role, now, horizon):
    return cr.validate_child_release(ctx, role, now, horizon)


def test_number_preserves_finite_values_and_types():
    for value in (0, 7, -7, 10 ** 300, 1.5, -2.25, 0.0):
        out = cr._number(value)
        assert out == value and type(out) is type(value)
    for bad in (True, False, None, "1", [1], {}, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match=MESSAGE):
            cr._number(bad)


@pytest.mark.parametrize("value", [HUGE, -HUGE])
def test_number_oversized_integer_refuses_cleanly(value):
    with pytest.raises(ValueError, match=MESSAGE):
        cr._number(value)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("which", ["now", "horizon"])
def test_caller_clock_refusal_precedes_authority_io(tmp_path, role, sign, which):
    ctx, now, _ = fixture(tmp_path, role)
    args = {"now": now, "horizon": now + 60}
    args[which] = sign * HUGE
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError, match=MESSAGE):
        _run(ctx, role, args["now"], args["horizon"])
    assert _snapshot(tmp_path) == before
    assert not Path(ctx["output_root"]).exists()
    # control: valid caller clocks accepted
    assert _run(ctx, role, now, now + 60)["output_root"] == ctx["output_root"]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("key", ["global_clock", "stage_clock"])
@pytest.mark.parametrize("bound", BOUNDS)
def test_hash_bound_clock_fields_refuse_without_writes(tmp_path, role, sign, key, bound):
    ctx, now, mutate = fixture(tmp_path, role)
    mutate(key, bound, sign * HUGE)
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError, match=MESSAGE):
        _run(ctx, role, now, now + 60)
    assert _snapshot(tmp_path) == before
    assert not Path(ctx["output_root"]).exists()


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("sign", [1, -1])
def test_stop_observation_uses_same_numeric_boundary(tmp_path, role, sign):
    ctx, now, mutate = fixture(tmp_path, role)
    mutate("mapping_stop", "observed_monotonic", sign * HUGE)
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError, match=MESSAGE):
        _run(ctx, role, now, now + 60)
    assert _snapshot(tmp_path) == before
    assert not Path(ctx["output_root"]).exists()


@pytest.mark.parametrize("role", ROLES)
def test_valid_release_and_temporal_fences_preserved(tmp_path, role):
    ctx, now, mutate = fixture(tmp_path, role)
    assert _run(ctx, role, now, now + 60)["output_root"] == ctx["output_root"]
    with pytest.raises(ValueError, match="expired, future or inconsistent clock"):
        _run(ctx, role, now, now + 10 ** 7)
    with pytest.raises(ValueError, match=MESSAGE):
        _run(ctx, role, True, now + 60)
    mutate("stage_clock", "deadline_epoch", 1.0e9)
    with pytest.raises(ValueError, match="expired, future or inconsistent clock"):
        _run(ctx, role, now, now + 60)

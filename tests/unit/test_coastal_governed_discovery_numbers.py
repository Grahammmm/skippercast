"""Caller clocks are validated before governed discovery reads authority metadata."""
import pytest

from skippercast.coastal import governed_discovery as gd

MESSAGE = "finite non-boolean clock required"
HUGE = 10 ** 400
BAD = [True, False, None, "5", "abc", [5], {"a": 1}, float("nan"),
       float("inf"), float("-inf"), HUGE, -HUGE]


def _ctx():
    return {"schema": gd.SCHEMA, "child_grant": {"execution_authorized": True,
            "output_partition_role": "discovery"}, "mission_id": "m"}


@pytest.fixture(autouse=True)
def no_authority_io(monkeypatch):
    calls = []

    def boom(name):
        def fail(*a, **k):
            calls.append(name)
            raise AssertionError(name + " called")
        return fail

    for name in ("_document", "validate_partition", "validate_output_plan", "_canonical"):
        monkeypatch.setattr(gd, name, boom(name))
    monkeypatch.setattr(gd.inventory, "inventory", boom("inventory"))
    monkeypatch.setattr(gd, "ManagedOutputs", boom("ManagedOutputs"))
    monkeypatch.setattr(gd.time, "time", lambda: 1000.0)
    monkeypatch.setattr(gd.time, "monotonic", lambda: 1000.0)
    return calls


@pytest.mark.parametrize("fn", ["validate", "run"])
@pytest.mark.parametrize("which", ["now", "horizon"])
@pytest.mark.parametrize("bad", BAD, ids=repr)
def test_malformed_caller_clock_refuses_before_authority_io(no_authority_io, fn, which, bad):
    args = {"now": 0, "horizon": 2000}
    args[which] = bad
    ctx = _ctx()
    before = repr(ctx)
    call = gd.validate if fn == "validate" else (lambda c, n, h: gd.run(c, now=n, horizon=h))
    with pytest.raises(ValueError, match=MESSAGE):
        call(ctx, args["now"], args["horizon"])
    assert no_authority_io == [] and repr(ctx) == before


def test_bad_clock_reported_before_invalid_context(no_authority_io):
    with pytest.raises(ValueError, match=MESSAGE):
        gd.validate({"schema": "wrong"}, False, 2000)
    assert no_authority_io == []


@pytest.mark.parametrize("now", [0, 0.0, 5, 5.5])
def test_valid_clock_types_reach_existing_context_checks(no_authority_io, now):
    with pytest.raises(ValueError, match="typed discovery context required"):
        gd.validate({"schema": "wrong"}, now, 2000)
    # a valid-typed context proceeds to the existing authority path (first seam)
    with pytest.raises(AssertionError, match="validate_partition"):
        gd.validate(_ctx(), now, 2000.5)
    assert no_authority_io == ["validate_partition"]

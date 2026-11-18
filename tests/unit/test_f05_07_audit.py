"""F05-07: ordered status reports the action step would actually permit.

Contract protected: Controller.status()["next"] and Controller.step() take their
decision from one read-only function (_permitted), so a durable common hold, an
unresolved admission intent and the native-only fence (set after mapping
recovery) read the same in both.
Believable bug: status calls select_next() directly, so with stop_reason=common_hold
it said next=ready/acquire while step stopped, and after recovery it advertised a
native acquire that step would never run (only the source-free drain is allowed).
"""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from skippercast.coastal.coordinator import ordered_trial as ot

NOW = 1_000_000.0
PREPARATION = {"deadline_epoch": NOW + 3600, "source_cutoff_epoch": NOW + 2400}
ACTION_REF = {"sha256": "a" * 64}
FRESH = [{} for _ in range(4)]
# window A qualified but unmapped: the source-free map is the only drain work
A_QUALIFIED = [{"acquire": "done", "qualify": "done"}, {}, {}, {}]


class Reached(Exception):
    """Raised by the stubbed preflight: step got past every decision gate."""


@pytest.fixture
def parts(monkeypatch):
    ctl = object.__new__(ot.Controller)
    ctl.root = Path("root")
    ctl.path = Path("root/control/ordered-x.json")
    ctl.descriptor = {"sha256": "p" * 64}
    ctl.preparation = dict(PREPARATION, source_reuse_contract=None, output_roots=[])
    ctl.clock = lambda: NOW
    ctl.monotonic = lambda: 0.0
    holder = SimpleNamespace(rows=FRESH, state={})
    ctl._state = lambda: holder.state
    ctl._clock_gate = lambda state, native=False: (NOW, 0.0)
    adapter = object.__new__(ot.RealAdapter)
    adapter.native = SimpleNamespace(root="n")
    adapter.mapping = None
    for name, value in dict(load=lambda *a, **k: {"preparation": ctl.descriptor, "stage": "map", "index": 0},
                            _descriptor=lambda ref, contract: ref, _inventoried=lambda *a: True,
                            inventory=lambda p: {}, require_larger_runtime=lambda p: None,
                            controller_lock=lambda p: nullcontext()).items():
        monkeypatch.setattr(ot, name, value)
    monkeypatch.setattr(ot.RealAdapter, "states", lambda self, p: holder.rows)
    monkeypatch.setattr(ot.RealAdapter, "accounting", lambda self, p: {})
    def preflight(self, p, decision, action):
        raise Reached
    monkeypatch.setattr(ot.RealAdapter, "preflight", preflight)
    return ctl, adapter, holder


def _arrange(holder, *, rows=FRESH, stop=None, intents=(), fenced=False):
    holder.rows = rows
    holder.state = dict(stop_reason=stop, intents=list(intents), **({"native_fenced": True} if fenced else {}))


def _step(ctl, adapter):
    try:
        return ctl.step(adapter, ACTION_REF)
    except Reached:
        return "reached-preflight"


@pytest.mark.parametrize("label,arrange,expected", [
    ("durable common hold", dict(stop="common_hold"), {"state": "stopped", "reason": "common_hold"}),
    ("unresolved admission intent", dict(intents=[{"action": {"sha256": "z" * 64}}]),
     {"state": "recovery_required", "reason": "unresolved durable admission"}),
    ("native fence, nothing to drain", dict(fenced=True), {"state": "native_fenced"}),
])
def test_status_next_equals_what_step_returns(parts, label, arrange, expected):
    ctl, adapter, holder = parts
    _arrange(holder, **arrange)
    assert ctl.status(adapter)["next"] == expected, label
    assert _step(ctl, adapter) == expected, label


def test_negative_control_unfenced_fresh_job_is_ready_acquire_in_both(parts):
    """Without a hold/fence the old answer (ready/acquire) is right, so the fix is not a blanket refusal."""
    ctl, adapter, holder = parts
    _arrange(holder)
    assert ctl.status(adapter)["next"] == dict(state="ready", stage="acquire", index=0)


def test_fenced_source_free_drain_is_allowed_by_status_and_step(parts):
    ctl, adapter, holder = parts
    _arrange(holder, rows=A_QUALIFIED, fenced=True)
    assert ctl.status(adapter)["next"] == dict(state="ready", stage="map", index=0)
    assert _step(ctl, adapter) == "reached-preflight"


def test_stop_wins_over_fence_drain_in_both(parts):
    ctl, adapter, holder = parts
    _arrange(holder, rows=A_QUALIFIED, fenced=True, stop="common_hold")
    assert ctl.status(adapter)["next"] == {"state": "stopped", "reason": "common_hold"}
    assert _step(ctl, adapter) == {"state": "stopped", "reason": "common_hold"}

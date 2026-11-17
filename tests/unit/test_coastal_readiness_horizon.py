"""Generic coastal readiness gate: invalid scheduling horizons fail closed (offline, pure)."""
import copy
import math

import pytest

from skippercast.coastal.coordinator.stages import readiness

CODE, DEPS = "c" * 8, "d" * 8


def _evidence(**over):
    ev = {"code_sha": CODE, "deps_sha": DEPS, "valid_until_epoch": 200,
          "dimensions": {"observation": "ready"}}
    ev.update(over)
    return ev


def _gate(ev=None, now=100, duration_s=50):
    return readiness("qualify", _evidence() if ev is None else ev, now=now,
                     duration_s=duration_s, code_sha=CODE, deps_sha=DEPS)


def test_healthy_control_and_expired_control():
    assert _gate() == (True, [])
    assert _gate(now=250) == (False, ["evidence_expired"])


@pytest.mark.parametrize("now,duration", [
    (250, math.nan), (250, -100), (100, 0), (250, math.inf), (250, -math.inf),
    (math.nan, 50), (math.inf, 50), (-math.inf, 50),
    (True, 50), (100, True), ("100", 50), (100, "50"), (None, 50), (100, None),
])
def test_invalid_now_or_duration_cannot_admit_evidence(now, duration):
    assert _gate(now=now, duration_s=duration) == (False, ["evidence_expired"])


@pytest.mark.parametrize("expires", [True, "200", None, math.nan, math.inf, -math.inf, 10 ** 400])
def test_expiry_operand_is_real_finite_number(expires):
    assert _gate(_evidence(valid_until_epoch=expires)) == (False, ["evidence_expired"])


@pytest.mark.parametrize("now,duration", [(10 ** 400, 50), (100, 10 ** 400), (1.7e308, 1.7e308)])
def test_huge_operands_and_overflowing_horizon_fail_closed(now, duration):
    assert _gate(now=now, duration_s=duration) == (False, ["evidence_expired"])


def test_valid_horizon_preserves_strict_boundary_without_mutation():
    ev = _evidence()
    before = copy.deepcopy(ev)
    assert _gate(ev, now=100, duration_s=99) == (True, [])
    assert _gate(ev, now=100, duration_s=100) == (False, ["evidence_expired"])
    assert _gate(ev, now=100, duration_s=101) == (False, ["evidence_expired"])
    assert _gate(ev, now=100.25, duration_s=99.5) == (True, [])
    assert _gate(_evidence(valid_until_epoch=-10), now=-100, duration_s=50.5) == (True, [])
    assert _gate(_evidence(valid_until_epoch=-10), now=-100, duration_s=90) == (False, ["evidence_expired"])
    assert ev == before


def test_other_holds_and_discover_contract_are_unchanged():
    ev = _evidence(holds=["zeta", "alpha"], code_sha="old", dimensions={})
    ok, holds = _gate(ev, now=250, duration_s=math.nan)
    assert not ok
    assert holds == sorted({"alpha", "zeta", "implementation_stale", "evidence_expired",
                            "dimension_not_ready"})
    assert readiness("discover", {"holds": ["h"]}, now=math.nan, duration_s=-1,
                     code_sha=CODE, deps_sha=DEPS) == (False, ["h"])
    assert readiness("discover", {}, now=math.nan, duration_s=-1,
                     code_sha=CODE, deps_sha=DEPS) == (True, [])

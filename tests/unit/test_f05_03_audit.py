"""F05-03 / SCA-256: a refused reservation must keep an observed clock rollback.

Contract: Budget.reserve() persists newly observed clock uncertainty before it
refuses, so a reopened ledger stays stopped after the clock catches up.
Believable bug it catches: reserve() raising "budget stopped" before saving
state, so the uncertainty flag is lost and later work is accepted.
"""
import json

import pytest

from skippercast.coastal.budget import Budget, Limits


class _Clock:
    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now

    def monotonic(self):
        return self.now


def _budget(tmp_path, clock):
    return Budget.create(tmp_path / "budget.json",
                         Limits(wall_s=10_000, bytes=100, requests=10, attempts_per_candidate=2),
                         clock=clock)


def _state(budget):
    return json.loads(budget.path.read_text())


def test_refused_reservation_keeps_observed_rollback(tmp_path):
    clock = _Clock(1000.0)
    budget = _budget(tmp_path, clock)
    budget.reserve("before", bytes=10, requests=1, candidate="c")
    before = _state(budget)

    clock.now = 900.0  # monotonic rollback observed inside the refused reserve
    with pytest.raises(ValueError, match="clock_uncertain"):
        budget.reserve("refused", bytes=10, requests=1, candidate="c")

    clock.now = 5000.0  # clock catches up; a new process reopens the ledger
    reopened = Budget.open(budget.path, clock=clock)
    assert _state(reopened)["clock_uncertain"] is True
    with pytest.raises(ValueError, match="clock_uncertain"):
        reopened.reserve("after", bytes=10, requests=1, candidate="c")
    assert reopened.decide().reason == "clock_uncertain"

    after = _state(reopened)
    for key in ("reserved", "charged", "reservations"):
        assert after[key] == before[key]
    assert "refused" not in after["reservations"] and "after" not in after["reservations"]


def test_monotone_clock_control_still_reserves(tmp_path):
    clock = _Clock(1000.0)
    budget = _budget(tmp_path, clock)
    clock.now = 1100.0
    assert budget.reserve("ok", bytes=10, requests=1, candidate="c")["state"] == "reserved"
    state = _state(Budget.open(budget.path, clock=clock))
    assert state["clock_uncertain"] is False
    assert state["reserved"]["bytes"] == 10 and "ok" in state["reservations"]

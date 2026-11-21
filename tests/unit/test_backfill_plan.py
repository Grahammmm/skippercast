"""Offline acceptance tests for the look-back planner and runner."""

import ast
import builtins
import inspect
import io
import os
import re
import socket
import subprocess
import sys
from datetime import date, datetime
from typing import Any

import pytest

from skippercast.pipeline import backfill_plan
from skippercast.pipeline.backfill_plan import BackfillResult, backfill_dates, run_backfill


TODAY = date(2026, 1, 4)
WEEK = [
    date(2025, 12, 28),
    date(2025, 12, 29),
    date(2025, 12, 30),
    date(2025, 12, 31),
    date(2026, 1, 1),
    date(2026, 1, 2),
    date(2026, 1, 3),
]


@pytest.mark.parametrize("days", range(1, 8))
def test_C1_window_is_ascending_and_excludes_today(days):
    # Catch off-by-one windows and arithmetic that fails across a year boundary.
    assert backfill_dates(TODAY, days) == WEEK[-days:]


def test_C1_skip_only_dates_already_held():
    # A one-shot iterable catches membership checks that consume later matches.
    have = iter([TODAY, WEEK[4], WEEK[1], WEEK[4], date(2025, 12, 27)])
    assert backfill_dates(TODAY, 7, have) == [WEEK[0], *WEEK[2:4], *WEEK[5:]]


def test_C1_complete_history_returns_empty_list():
    assert backfill_dates(TODAY, 7, WEEK) == []


def test_C1_do_not_underflow_the_calendar():
    assert backfill_dates(date(1, 1, 2), 7) == [date.min]
    assert backfill_dates(date.min, 7) == []


@pytest.mark.parametrize("today", [datetime(2026, 1, 4), "2026-01-04"])
def test_C1_reject_datetime_and_non_date(today):
    # datetime is a date subclass; accepting it would silently truncate time.
    with pytest.raises(TypeError) as caught:
        backfill_dates(today, 1)
    assert caught.type is TypeError


@pytest.mark.parametrize("days", [True, False, 0, -1, 8, 1.0, "7", None])
def test_C1_reject_invalid_days_and_name_the_value(days):
    # True compares equal to 1, and a float or string must not be coerced.
    with pytest.raises(ValueError, match=rf"{re.escape(repr(days))}$") as caught:
        backfill_dates(TODAY, days)
    assert caught.type is ValueError


def test_C2_preserve_call_order_and_continue_past_absence():
    # Unsorted input and a falsy payload catch sorting and dropped successes.
    calls = []
    client, bounds = object(), object()
    last, missing, first = WEEK[-1], WEEK[3], WEEK[0]
    payload = object()
    message = f"no observation for {missing}"

    def fetch(actual_client, actual_bounds, day):
        calls.append((actual_client, actual_bounds, day))
        if day == missing:
            raise ValueError(message)
        return None if day == last else payload

    assert run_backfill(fetch, client, bounds, iter([last, missing, first])) == BackfillResult(
        [(last, None), (first, payload)], [(missing, message)]
    )
    assert calls == [(client, bounds, last), (client, bounds, missing), (client, bounds, first)]


def test_C2_propagate_the_original_non_value_error_and_stop():
    # A prior success must not turn a fatal exception into a partial result.
    calls = []
    failure = RuntimeError("fixture fetch failed")
    client, bounds = object(), object()

    def fetch(actual_client, actual_bounds, day):
        calls.append((actual_client, actual_bounds, day))
        if day == WEEK[1]:
            raise failure
        return "fixture payload"

    with pytest.raises(RuntimeError) as caught:
        run_backfill(fetch, client, bounds, WEEK)
    assert caught.type is RuntimeError
    assert caught.value is failure
    assert calls == [(client, bounds, WEEK[0]), (client, bounds, WEEK[1])]


def test_C2_empty_plan_never_calls_fetch():
    def fetch(client, bounds, day):
        pytest.fail("empty plan called the fetch")

    assert run_backfill(fetch, object(), object(), []) == BackfillResult([], [])


def test_C3_import_and_run_without_adapters_or_io(monkeypatch):
    # Catch a direct adapter import even if the fake would mask it during the run.
    tree = ast.parse(inspect.getsource(backfill_plan))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and (node.module or "").split(".")[0] in sys.stdlib_module_names

    # Guard the fresh module body as well as the calls against direct I/O.
    def unexpected_io(*args, **kwargs):
        pytest.fail("backfill performed I/O outside the injected fetch")

    namespace: dict[str, Any] = {"__name__": backfill_plan.__name__}
    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"), (builtins, "print"), (io, "open"), (os, "open"),
            (socket, "socket"), (subprocess, "Popen"),
        ):
            patch.setattr(owner, name, unexpected_io)
        exec(compile(tree, "backfill_plan.py", "exec"), namespace)
        dates = namespace["backfill_dates"](TODAY, 1)
        assert namespace["run_backfill"](lambda client, bounds, day: day, None, None, dates) == (
            BackfillResult([(WEEK[-1], WEEK[-1])], [])
        )

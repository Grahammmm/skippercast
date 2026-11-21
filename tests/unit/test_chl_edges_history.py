"""Offline contracts for the chlorophyll-edge history index."""

import io
import os
import socket
from datetime import date
from typing import Any

import pytest

from skippercast.pipeline.chl_edges_history import (
    ChlEdgesIndexUpdate,
    dated_chl_edges_path,
    next_chl_edges_index,
)


TODAY = "2024-03-03"
NEW_SHA = "a" * 64
OLD_SHA = "0123456789abcdef" * 4


def _row(day: str, digest: str = OLD_SHA) -> dict[str, str]:
    return {"date": day, "path": f"chl-edges/{day}.json", "sha256": digest}


def _update(
    *index: dict[str, str], dropped: tuple[tuple[int, str], ...] = (),
) -> ChlEdgesIndexUpdate:
    return ChlEdgesIndexUpdate(list(index), frozenset(row["path"] for row in index), dropped)


def test_c1_dated_path() -> None:
    """A valid leap day uses the chl-edges prefix, not the SST fronts prefix."""
    assert dated_chl_edges_path("2024-02-29") == "chl-edges/2024-02-29.json"


@pytest.mark.parametrize("day", [None, "20240229", "2024-W09-4", "2024-2-29", "2024-02-29\n", "2023-02-29"])
def test_c1_reject_invalid_date(day: Any) -> None:
    """Reject noncanonical ISO spellings and calendar dates that do not exist."""
    with pytest.raises(ValueError) as error:
        dated_chl_edges_path(day)
    assert error.type is ValueError


@pytest.mark.parametrize("previous", [None, []])
def test_c2_first_day(previous: object) -> None:
    """Absent and empty history both start an index without a spurious drop."""
    assert next_chl_edges_index(previous, TODAY, NEW_SHA, TODAY) == _update(_row(TODAY, NEW_SHA))


@pytest.mark.parametrize("keep_days", [None, 7])
def test_c2_seven_day_window(keep_days: int | None) -> None:
    """Age six is retained across leap day; age seven and future rows are silently trimmed."""
    kept = [_row(day) for day in (
        "2024-03-02", "2024-03-01", "2024-02-29", "2024-02-28", "2024-02-27", "2024-02-26",
    )]
    previous = [_row("2024-03-04"), *reversed(kept), _row("2024-02-25")]
    result = (next_chl_edges_index(previous, TODAY, NEW_SHA, TODAY) if keep_days is None
              else next_chl_edges_index(previous, TODAY, NEW_SHA, TODAY, keep_days=keep_days))
    assert result == _update(_row(TODAY, NEW_SHA), *kept)


def test_c2_one_day_window() -> None:
    """A one-day window keeps only today, not yesterday or missing-day fillers."""
    previous = [_row("2024-03-02"), _row("2024-02-26")]
    assert next_chl_edges_index(previous, TODAY, NEW_SHA, TODAY, keep_days=1) == _update(_row(TODAY, NEW_SHA))


def test_c2_backfill_at_oldest_boundary() -> None:
    """A new row may be six days old and must slot below newer rows without filling gaps."""
    assert next_chl_edges_index([_row(TODAY)], "2024-02-26", NEW_SHA, TODAY) == _update(
        _row(TODAY), _row("2024-02-26", NEW_SHA),
    )


@pytest.mark.parametrize(("field", "value", "message"), [
    ("day", None, "expected a YYYY-MM-DD date"),
    ("today", "20240303", "expected a YYYY-MM-DD date"),
    ("day", "2024-03-04", "day is outside the keep window"),
    ("day", "2024-02-25", "day is outside the keep window"),
    ("keep_days", 0, "keep_days must be an integer in 1..7"),
    ("keep_days", 8, "keep_days must be an integer in 1..7"),
    ("keep_days", True, "keep_days must be an integer in 1..7"),
    ("keep_days", 1.0, "keep_days must be an integer in 1..7"),
    ("sha256", None, "sha256 must be 64 lowercase hex characters"),
    ("sha256", "a" * 63, "sha256 must be 64 lowercase hex characters"),
    ("sha256", "A" * 64, "sha256 must be 64 lowercase hex characters"),
    ("sha256", NEW_SHA + "\n", "sha256 must be 64 lowercase hex characters"),
])
def test_c2_reject_invalid_arguments(field: str, value: object, message: str) -> None:
    """Bad caller input raises the fronts-rule error instead of returning a dropped row."""
    arguments: dict[str, Any] = {"day": TODAY, "sha256": NEW_SHA, "today": TODAY, "keep_days": 7}
    arguments[field] = value
    with pytest.raises(ValueError) as error:
        next_chl_edges_index(None, **arguments)
    assert error.type is ValueError
    assert str(error.value) == message


@pytest.mark.parametrize("field", ["day", "today"])
def test_c2_preserve_calendar_error(field: str) -> None:
    """Both date arguments pass through the calendar parser's error, like the fronts rule."""
    impossible = "2024-02-30"
    with pytest.raises(ValueError) as calendar_error:
        date.fromisoformat(impossible)
    day = impossible if field == "day" else TODAY
    today = impossible if field == "today" else TODAY
    with pytest.raises(ValueError) as error:
        next_chl_edges_index(None, day, NEW_SHA, today)
    assert error.type is ValueError
    assert str(error.value) == str(calendar_error.value)


@pytest.mark.parametrize("previous", [{}, (), "", 0])
def test_c2_report_non_list_history(previous: object) -> None:
    """Even falsy non-list history gets a sentinel instead of being treated as absent."""
    assert next_chl_edges_index(previous, TODAY, NEW_SHA, TODAY) == _update(
        _row(TODAY, NEW_SHA), dropped=((-1, "not a list"),),
    )


def test_c2_report_drop_reasons_in_input_order() -> None:
    """Report the first defect at each original offset, even on a row too old to keep."""
    day = "2024-03-02"
    good = _row(day)
    previous = [
        None,
        {"date": "2024-02-30", "sha256": "wrong"},
        good | {"sha256": "wrong", "path": "wrong"},
        good | {"path": f"sst-fronts/{day}.json"},
        good | {"extra": "not part of the index"},
        good | {"path": f"chl-edges/{TODAY}.json"},
        _row(day, "b" * 64),
        _row("2024-02-25", "wrong"),
    ]
    assert next_chl_edges_index(previous, TODAY, NEW_SHA, TODAY) == _update(
        _row(TODAY, NEW_SHA), good,
        dropped=((0, "not a dict"), (1, "bad date"), (2, "bad sha256"), (3, "bad path"),
                 (5, "bad path"), (6, "duplicate date"), (7, "bad sha256")),
    )


def test_c3_replace_backfill_without_io_or_input_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replacing, sorting, and projecting rows must not edit the input or touch disk/network."""
    backfill = "2024-03-01"
    newer = "2024-03-02"
    before = [_row(backfill), _row(newer) | {"extra": "leave this alone"}]
    previous = [row.copy() for row in before]

    def unexpected_io(*args: object, **kwargs: object) -> None:
        pytest.fail("the history rule attempted I/O")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", unexpected_io)
        patch.setattr(io, "open", unexpected_io)
        patch.setattr(os, "open", unexpected_io)
        patch.setattr(socket, "socket", unexpected_io)
        path = dated_chl_edges_path(backfill)
        result = next_chl_edges_index(previous, backfill, NEW_SHA, TODAY)

    assert path == "chl-edges/2024-03-01.json"
    assert result == _update(_row(newer), _row(backfill, NEW_SHA))
    assert previous == before

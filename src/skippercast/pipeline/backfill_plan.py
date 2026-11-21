"""Plan look-back dates and run a caller-supplied fetch for each date."""

from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import NamedTuple, TypeVar


_Client = TypeVar("_Client")
_Bounds = TypeVar("_Bounds")

BackfillResult = NamedTuple(
    "BackfillResult", [("fetched", list[tuple[date, object]]), ("absent", list[tuple[date, str]])]
)


def backfill_dates(today: date, days: int, have: Iterable[date] = ()) -> list[date]:
    """Return missing calendar dates in ascending order, excluding today."""
    if isinstance(today, datetime) or not isinstance(today, date):
        raise TypeError("today must be a date, not a datetime")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 7:
        raise ValueError(f"days must be an integer from 1 to 7, got {days!r}")

    # Bound the window at the first representable date to avoid underflow.
    end = today.toordinal()
    window = map(date.fromordinal, range(max(1, end - days), end))
    existing = set(have)
    return [day for day in window if day not in existing]


def run_backfill(
    fetch_for_date: Callable[[_Client, _Bounds, date], object],
    client: _Client,
    bounds: _Bounds,
    dates: Iterable[date],
) -> BackfillResult:
    """Collect results in input order, recording ValueError as an absent day."""
    fetched: list[tuple[date, object]] = []
    absent: list[tuple[date, str]] = []
    for day in dates:
        try:
            value = fetch_for_date(client, bounds, day)
        except ValueError as exc:
            absent.append((day, str(exc)))
        else:
            fetched.append((day, value))
    return BackfillResult(fetched, absent)

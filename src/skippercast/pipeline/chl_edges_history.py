"""Pure path and index rules for dated chlorophyll-edge history."""

import re
from datetime import date
from typing import NamedTuple, TypeGuard


_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ChlEdgesIndexUpdate(NamedTuple):
    index: list[dict[str, str]]  # pyright: ignore[reportIncompatibleMethodOverride]
    keep: frozenset[str]
    dropped: tuple[tuple[int, str], ...]


def _parse_day(day: object) -> date:
    if not isinstance(day, str) or not _DAY.fullmatch(day):
        raise ValueError("expected a YYYY-MM-DD date")
    return date.fromisoformat(day)


def _path(day: date) -> str:
    return f"chl-edges/{day.isoformat()}.json"


def dated_chl_edges_path(day: str) -> str:
    """Return the region-relative path for a canonical calendar date."""
    return _path(_parse_day(day))


def _valid_sha256(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _previous_entry(entry: object, seen: dict[date, dict[str, str]]) -> tuple[date, dict[str, str]]:
    if not isinstance(entry, dict):
        raise ValueError("not a dict")
    try:
        day = _parse_day(entry.get("date"))
    except ValueError:
        raise ValueError("bad date") from None
    digest = entry.get("sha256")
    if not _valid_sha256(digest):
        raise ValueError("bad sha256")
    path = _path(day)
    if entry.get("path") != path:
        raise ValueError("bad path")
    if day in seen:
        raise ValueError("duplicate date")
    return day, {"date": day.isoformat(), "path": path, "sha256": digest}


def next_chl_edges_index(
    previous: object, day: str, sha256: str, today: str, keep_days: int = 7,
) -> ChlEdgesIndexUpdate:
    """Compute the next index without changing the previous index or any files."""
    current = _parse_day(day)
    end = _parse_day(today)
    if not isinstance(keep_days, int) or isinstance(keep_days, bool) or not 1 <= keep_days <= 7:
        raise ValueError("keep_days must be an integer in 1..7")
    if not 0 <= (end - current).days < keep_days:
        raise ValueError("day is outside the keep window")
    if not _valid_sha256(sha256):
        raise ValueError("sha256 must be 64 lowercase hex characters")

    entries: dict[date, dict[str, str]] = {}
    dropped: list[tuple[int, str]] = []
    if isinstance(previous, list):
        for position, entry in enumerate(previous):
            try:
                previous_day, clean = _previous_entry(entry, entries)
            except ValueError as exc:
                dropped.append((position, str(exc)))
            else:
                entries[previous_day] = clean
    elif previous is not None:
        dropped.append((-1, "not a list"))

    entries[current] = {"date": day, "path": _path(current), "sha256": sha256}
    index = [entries[d] for d in sorted(entries, reverse=True) if 0 <= (end - d).days < keep_days]
    return ChlEdgesIndexUpdate(index, frozenset(e["path"] for e in index), tuple(dropped))

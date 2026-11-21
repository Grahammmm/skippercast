"""Pure manifest history selection for observed habitat layers."""

import re
from datetime import date
from itertools import chain
from typing import NamedTuple, TypeGuard

# Wire limits and grammar from web/map/habitat-feed.ts.
_MAX_DAYS = 7
_MAX_TILES = 64
_MAX_TILE_BYTES = 5_000_000
_PATH = re.compile(r"habitat-history/[a-z0-9-]+-[a-f0-9]{16}\.json")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_SAMPLE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])"
    r"(?:\.([0-9]{1,3}))?(Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


class HistoryUpdate(NamedTuple):
    history: list[dict]
    keep_paths: frozenset[str]
    dropped: list[tuple[int, str]]


def _instant(sample: object) -> int | None:
    """Return a comparable millisecond instant, using the reader's calendar."""
    match = _SAMPLE.fullmatch(sample) if isinstance(sample, str) else None
    if match is None:
        return None
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    fraction, zone = match.group(7, 8)
    try:
        # JS accepts year 0000. Shift that leap year by one Gregorian cycle
        # for date validation, then subtract the cycle from its ordinal.
        ordinal = date(year or 400, month, day).toordinal()
    except ValueError:
        return None
    if year == 0:
        ordinal -= 146_097
    minutes = ordinal * 1440 + hour * 60 + minute
    if zone != "Z":
        offset = int(zone[1:3]) * 60 + int(zone[4:6])
        minutes -= offset if zone[0] == "+" else -offset
    return (minutes * 60 + second) * 1000 + int((fraction or "0").ljust(3, "0"))


def _number(value: object) -> TypeGuard[int | float]:
    # Both callers bound the values, ruling out non-finite floats as well.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _box(bounds: object) -> bool:
    if not isinstance(bounds, list) or len(bounds) != 4 or not all(map(_number, bounds)):
        return False
    west, south, east, north = bounds
    return -180 <= west < east <= 180 and -90 <= south < north <= 90


def _tile_ref(ref: object) -> bool:
    if not isinstance(ref, dict):
        return False
    path, digest, size = ref.get("path"), ref.get("sha256"), ref.get("bytes")
    return (
        isinstance(path, str) and _PATH.fullmatch(path) is not None
        and isinstance(digest, str) and _SHA256.fullmatch(digest) is not None
        and _number(size) and 1 <= size <= _MAX_TILE_BYTES
        and (isinstance(size, int) or size.is_integer())
        and ("bounds" not in ref or _box(ref["bounds"]))
    )


def entry_problem(entry: object) -> str | None:
    """Return the first structural rejection reason for one history entry."""
    if not isinstance(entry, dict):
        return "not-object"
    if _instant(entry.get("sample_at")) is None:
        return "sample_at"
    tiles = entry.get("tiles")
    if not isinstance(tiles, list) or not 1 <= len(tiles) <= _MAX_TILES:
        return "tiles"
    if not all(map(_tile_ref, tiles)):
        return "tile-ref"
    if len({ref["path"] for ref in tiles}) != len(tiles):
        return "duplicate-path"
    return None


def next_history(
    previous: object, outgoing: object, current_sample_at: object, *, discard: bool = False,
) -> HistoryUpdate:
    """Select the newest valid prior instants and collect their referenced paths."""
    current = _instant(current_sample_at)
    if current is None:
        raise ValueError("current_sample_at")
    if discard:
        return HistoryUpdate([], frozenset(), [])

    prior = previous if isinstance(previous, list) else []
    candidates = chain(() if outgoing is None else ((-1, outgoing),), enumerate(prior))
    by_time: dict[int, tuple[int, dict]] = {}
    dropped: list[tuple[int, str]] = []
    for index, entry in candidates:
        problem = entry_problem(entry)
        if problem is not None:
            dropped.append((index, problem))
            continue
        assert isinstance(entry, dict)
        time = _instant(entry["sample_at"])
        assert time is not None
        if time >= current:
            dropped.append((index, "not-older"))
        elif time in by_time:
            dropped.append((index, "duplicate-day"))
        else:
            by_time[time] = index, {"sample_at": entry["sample_at"], "tiles": entry["tiles"]}

    ordered = [by_time[time] for time in sorted(by_time, reverse=True)]
    history = [entry for _, entry in ordered[:_MAX_DAYS]]
    dropped.extend((index, "beyond-7") for index, _ in ordered[_MAX_DAYS:])
    keep_paths = frozenset(ref["path"] for entry in history for ref in entry["tiles"])
    return HistoryUpdate(history, keep_paths, sorted(dropped))

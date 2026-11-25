"""Attach observation history to a layer manifest without publishing it."""

import math
import re
from datetime import datetime, timezone


_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_HOUR = r"(?:[01][0-9]|2[0-3])"
_MINUTE = r"[0-5][0-9]"
_INSTANT = re.compile(
    rf"{_DAY.pattern}T{_HOUR}:{_MINUTE}:{_MINUTE}"
    rf"(?:\.[0-9]{{1,3}})?(?:Z|[+-]{_HOUR}:{_MINUTE})"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _instant_ms(value: object, *, date_only: bool = False) -> int | None:
    if not isinstance(value, str):
        return None
    if date_only and _DAY.fullmatch(value):
        value += "T00:00:00Z"
    if not _INSTANT.fullmatch(value):
        return None
    # The reader supports ISO year 0000; datetime starts at year 1.
    year_zero = value.startswith("0000-")
    if year_zero:
        value = "0400" + value[4:]
    try:
        elapsed = datetime.fromisoformat(value) - _EPOCH
    except ValueError:
        return None
    days = elapsed.days - (146097 if year_zero else 0)  # One Gregorian cycle.
    return (days * 86400 + elapsed.seconds) * 1000 + elapsed.microseconds // 1000


def _number(value: object) -> float | None:
    # Match Number.isFinite on manifest numbers, not Python's bool-as-int rule.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _current_ms(layer: dict) -> float | int:
    frames = layer.get("frames")
    if not isinstance(frames, list):
        raise ValueError("layer")
    latest = None
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("layer")
        time = _number(frame.get("time"))
        if time is None:
            raise ValueError("layer")
        count = _number(frame.get("valid_cells"))
        if count is not None and count <= 0:
            continue
        if latest is None or time > latest:
            latest = time
    current = latest * 1000 if latest is not None else _instant_ms(layer.get("sample_at"), date_only=True)
    if current is None or not math.isfinite(current):
        raise ValueError("layer")
    return current


def with_history(layer: dict, history: list[dict]) -> dict:
    """Return a new layer manifest with its history replaced or removed."""
    if not history:
        return {key: value for key, value in layer.items() if key != "history"}
    if layer.get("kind") == "forecast":
        raise ValueError("forecast")
    current = _current_ms(layer)
    too_recent = False
    for entry in history:
        time = _instant_ms(entry.get("sample_at"))
        if time is None:
            raise ValueError("sample_at")
        # Check every entry's grammar before reporting a chronology error.
        too_recent |= time >= current
    if too_recent:
        raise ValueError("current")
    return {**layer, "history": history}

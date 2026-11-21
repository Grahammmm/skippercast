"""Offline checks for one manifest layer's history tile bodies."""

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import NoReturn

_HISTORY_PATH = re.compile(r"habitat-history/[a-z0-9-]+-[a-f0-9]{16}\.json")
_SAMPLE_AT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,3})?(Z|([+-])([0-9]{2}):([0-9]{2}))"
)


def _epoch_seconds(sample_at: str) -> float | None:
    match = _SAMPLE_AT.fullmatch(sample_at)
    if match is None:
        return None
    zone, sign, hours, minutes = match.groups()
    offset = 0
    if zone != "Z":
        hour, minute = int(hours), int(minutes)
        if hour > 23 or minute > 59:
            return None
        offset = (hour * 60 + minute) * 60 * (-1 if sign == "-" else 1)
    local = sample_at[:match.start(1)]
    # Date.parse supports year 0000. Year 0400 has the same Gregorian calendar.
    year_zero = local.startswith("0000")
    try:
        when = datetime.fromisoformat("0400" + local[4:] if year_zero else local)
    except ValueError:
        return None
    delta = when - datetime(1970, 1, 1)
    days = delta.days - (146097 if year_zero else 0)
    return ((days * 86400 + delta.seconds - offset) * 1000 + delta.microseconds // 1000) / 1000


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and -math.inf < value < math.inf


def _box(bounds: object) -> bool:
    if not isinstance(bounds, list) or len(bounds) != 4 or not all(map(_number, bounds)):
        return False
    west, south, east, north = bounds
    return -180 <= west < east <= 180 and -90 <= south < north <= 90


def _row_ok(row: object, width: int) -> bool:
    return (
        isinstance(row, list) and len(row) == width and width >= 2
        and _number(row[0]) and _number(row[1])
        and all(value is None or isinstance(value, bool) or _number(value) for value in row)
    )


def _invalid_constant(token: str) -> NoReturn:
    # Python's decoder otherwise accepts NaN and Infinity, unlike JSON.parse.
    raise ValueError(f"Invalid JSON constant: {token}")


def _tile_reason(target: Path, region_id: str, layer: dict, ref: dict, epoch: float) -> str | None:
    name = ref.get("path")
    if not isinstance(name, str) or _HISTORY_PATH.fullmatch(name) is None:
        return "path"
    try:
        data = (target / name).read_bytes()
    except OSError:
        return "missing"
    size = ref.get("bytes")
    if not _number(size) or not 1 <= size <= 5_000_000 or len(data) != size:
        return "bytes"
    if hashlib.sha256(data).hexdigest() != ref.get("sha256"):
        return "sha256"
    try:
        # Match TextDecoder's BOM handling and JSON.parse's binary64 numbers.
        tile = json.loads(data.decode("utf-8-sig", errors="replace"),
                          parse_int=float, parse_constant=_invalid_constant)
    except ValueError:
        return "identity"
    if not isinstance(tile, dict):
        return "identity"
    version = tile.get("schema_version")
    bounds = tile.get("bounds")
    resolution = tile.get("resolution_degrees")
    if (
        not _number(version) or version != 1 or tile.get("region_id") != region_id
        or tile.get("layer_id") != layer["id"] or tile.get("fields") != layer["fields"]
        or not isinstance(resolution, list) or not all(map(_number, resolution))
        or resolution != layer["resolution_degrees"] or not _box(bounds)
        or ("bounds" in ref and (not _box(ref["bounds"]) or bounds != ref["bounds"]))
    ):
        return "identity"
    frames = tile.get("frames")
    if not isinstance(frames, list) or len(frames) != 1 or not isinstance(frames[0], dict):
        return "frames"
    time = frames[0].get("time")
    cells = frames[0].get("cells")
    if not _number(time) or time != epoch or not isinstance(cells, list):
        return "frames"
    if not all(_row_ok(row, len(layer["fields"])) for row in cells):
        return "frames"
    return None


def verify_history(target: Path, region_id: str, layer: dict, history: list[dict]) -> list[tuple[str, str]]:
    """Return the first tile refusal for each rejected day, in input order."""
    refusals = []
    for day in history:
        sample_at = day["sample_at"]
        epoch = _epoch_seconds(sample_at)
        if epoch is None:
            refusals.append((sample_at, "sample_at"))
            continue
        for ref in day["tiles"]:
            reason = _tile_reason(target, region_id, layer, ref, epoch)
            if reason is not None:
                refusals.append((sample_at, reason))
                break
    return refusals

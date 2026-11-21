"""Local file writer for dated SST fronts history."""

import json
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple

from skippercast.pipeline.fronts_history import dated_fronts_path, next_fronts_index
from skippercast.platform.contracts import atomic_json


class FrontsHistoryError(ValueError):
    """The live fronts document is invalid or conflicts with immutable history."""


class FrontsHistoryWrite(NamedTuple):
    index: list[dict[str, str]]  # pyright: ignore[reportIncompatibleMethodOverride]
    wrote_dated: bool
    stale: tuple[str, ...]
    dropped: tuple[tuple[int, str], ...]


def _stale_names(history_dir: Path, keep: frozenset[str]) -> tuple[str, ...]:
    stale = []
    for path in history_dir.glob("*.json"):
        if not path.is_file():
            continue
        try:
            relative_path = dated_fronts_path(path.stem)
        except ValueError:
            continue
        if relative_path not in keep:
            stale.append(path.name)
    return tuple(sorted(stale))


def write_fronts_history(
    region_dir: str | Path, day: str, today: str, keep_days: int = 7,
) -> FrontsHistoryWrite:
    """Archive the live fronts document and report stale files without pruning them."""
    region_dir = Path(region_dir)
    try:
        source = (region_dir / "sst-fronts.json").read_bytes()
        document = json.loads(source)
    except (OSError, ValueError) as exc:
        raise FrontsHistoryError("cannot read the live SST fronts document") from exc
    if (
        not isinstance(document, dict)
        or document.get("layer_id") != "sst-fronts"
        or document.get("region_id") != region_dir.name
    ):
        raise FrontsHistoryError("live SST fronts document does not match the layer and region")

    history_dir = region_dir / "sst-fronts"
    index_path = history_dir / "index.json"
    unreadable = ()
    try:
        previous = json.loads(index_path.read_bytes())
    except FileNotFoundError:
        previous = None
    except (OSError, ValueError):
        previous = None
        unreadable = ((-1, "unreadable"),)
    update = next_fronts_index(previous, day, sha256(source).hexdigest(), today, keep_days)

    dated_path = region_dir / dated_fronts_path(day)
    try:
        existing = dated_path.read_bytes()
    except FileNotFoundError:
        wrote_dated = True
    else:
        if existing != source:
            raise FrontsHistoryError(f"dated SST fronts file differs: {dated_path.name}")
        wrote_dated = False

    if wrote_dated:
        history_dir.mkdir(exist_ok=True)
        with dated_path.open("xb") as dated_file:
            dated_file.write(source)
    atomic_json(index_path, update.index, unique_tmp=True)
    return FrontsHistoryWrite(
        update.index, wrote_dated, _stale_names(history_dir, update.keep), unreadable + update.dropped,
    )

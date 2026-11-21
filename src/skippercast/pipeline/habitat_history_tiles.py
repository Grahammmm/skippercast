"""Offline materialization and retention of single-frame habitat tiles."""

from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

_HISTORY = "habitat-history"
_LAYER_ID = re.compile(r"[a-z0-9-]+")
_HISTORY_NAME = re.compile(rf"{_LAYER_ID.pattern}-[0-9]{{8}}-[a-f0-9]{{16}}\.json")
_TILE_KEYS = {"region_id", "layer_id", "bounds", "fields", "frames"}


def history_tile(tile: dict, frame_time: int) -> tuple[bytes, dict]:
    """Encode a published tile with exactly the requested epoch-second frame."""
    if not isinstance(frame_time, int) or isinstance(frame_time, bool):
        raise ValueError("time")
    if not isinstance(tile, dict) or tile.get("schema_version") != 1 or not _TILE_KEYS <= tile.keys():
        raise ValueError("tile")
    layer_id = tile["layer_id"]
    if not isinstance(layer_id, str) or not _LAYER_ID.fullmatch(layer_id):
        raise ValueError("tile")
    frames = [frame for frame in tile["frames"] if frame["time"] == frame_time]
    if len(frames) != 1:
        raise ValueError("frame")

    item = {**tile, "frames": frames}
    data = (json.dumps(item, separators=(",", ":"), allow_nan=False) + "\n").encode()
    sha = hashlib.sha256(data).hexdigest()
    day = datetime.fromtimestamp(frame_time, timezone.utc).date().isoformat().replace("-", "")
    return data, {
        "path": f"{_HISTORY}/{layer_id}-{day}-{sha[:16]}.json",
        "sha256": sha,
        "bytes": len(data),
        "bounds": tile["bounds"],
    }


def write_history_tile(target: Path, tile: dict, frame_time: int) -> dict:
    """Write a new tile without rewriting an existing matching tile."""
    data, ref = history_tile(tile, frame_time)
    path = target / ref["path"]
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("immutable")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("immutable")
        return ref

    path.parent.mkdir(parents=True, exist_ok=True)
    # Use a fresh sibling so a stale .tmp can't be overwritten or followed.
    with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as tmp:
        tmp.write(data)
    Path(tmp.name).replace(path)
    return ref


def prune_history(target: Path, keep: Iterable[str]) -> list[str]:
    """Delete unreferenced history files and return their sorted basenames."""
    kept = set()
    for name in keep:
        if not name.startswith(f"{_HISTORY}/") or ".." in name.split("/") or name == f"{_HISTORY}/":
            raise ValueError("keep")
        kept.add(name)

    folder = target / _HISTORY
    if folder.is_symlink() or not folder.is_dir():
        return []
    removed = []
    for path in folder.iterdir():
        if (_HISTORY_NAME.fullmatch(path.name) and f"{_HISTORY}/{path.name}" not in kept
                and not path.is_symlink() and path.is_file()):
            path.unlink()
            removed.append(path.name)
    return sorted(removed)

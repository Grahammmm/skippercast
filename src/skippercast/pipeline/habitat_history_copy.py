"""Carry referenced habitat history tiles forward to a new run."""

import hashlib
import re
from pathlib import Path

_HISTORY_TILE_PATH = re.compile(r"habitat-history/[a-z0-9-]+-[a-f0-9]{16}\.json")


def copy_previous_history(history: list[dict], prior_dir: Path, target: Path) -> list[str]:
    """Verify each reference and carry each distinct path forward in first-seen order."""
    tiles = [tile for entry in history for tile in entry["tiles"]]
    for tile in tiles:
        name = tile["path"]
        if not isinstance(name, str) or not _HISTORY_TILE_PATH.fullmatch(name):
            raise ValueError("path")

    carried: dict[str, None] = {}
    for tile in tiles:
        name = tile["path"]
        source = prior_dir / name
        data = source.read_bytes()
        if len(data) != tile["bytes"] or hashlib.sha256(data).hexdigest() != tile["sha256"]:
            raise ValueError("integrity")
        if name not in carried:
            dest = target / name
            if dest.resolve() != source.resolve():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            carried[name] = None
    return list(carried)

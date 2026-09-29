"""Where the SkipperCast repository (regions/, catalog/, dist/, var/) lives.

`SKIPPERCAST_ROOT` names it explicitly, so an installed package or a job run
from another directory reads the right tree. Without it, the root is the source
checkout this package was imported from (`src/skippercast/` → two levels up),
which is how every job and test has always run.
"""
import os
from pathlib import Path


def repo_root() -> Path:
    """The repository root: `$SKIPPERCAST_ROOT` when set, else this source checkout."""
    configured = os.environ.get("SKIPPERCAST_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]

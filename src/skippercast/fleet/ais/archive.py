"""``python -m skippercast.fleet.ais archive``: the long-term copy of the raw day files (design.md section 11).

The raw store keeps ``thresholds.retention.raw_days`` of positions, then empties them in place
(store.py). Labelling, reprocessing and the fishing-grounds history need older days, so this command
copies every closed day file (``raw/YYYY-MM-DD.sqlite`` with a day before today, UTC) to an archive
directory outside the store, with SQLite's online backup API (consistent while the listener writes).

Rules:

- a day already in the archive is replaced only when the store's copy holds MORE rows (late
  receipts). The rows are counted in the staged snapshot itself, so a store file that retention
  empties (even mid-run) never overwrites a fuller archive copy;
- today's file is never copied (it is still being written);
- nothing is ever deleted from the archive, and the store is only read;
- one run at a time per archive directory (a lock file); a second run copies nothing and exits 1;
- before copying, the archive's file system must keep ``--min-free-gb`` (finite, >= 0) free after
  the snapshots it will write (each day file plus its ``-wal``); otherwise it copies nothing and
  exits 1. Days the archive already holds in full cost nothing;
- the copies hold vessel identifiers and positions: directories this command creates are 0700 and
  the copies 0600, whatever the umask.

The archive directory comes from ``--dest`` or ``$SKIPPERCAST_FLEET_ARCHIVE`` (``<dest>/<region>/``
holds the day files). Output is one JSON line of counts; no positions, MMSIs or times.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from .store import DAY_FILE, TABLES, ais_root

__all__ = ["ArchiveResult", "archive", "main"]

ENV = "SKIPPERCAST_FLEET_ARCHIVE"
DEFAULT_MIN_FREE_GB = 50.0
LOCK = ".archive.lock"


@dataclass
class ArchiveResult:
    files: int = 0          # closed day files in the store
    copied: int = 0         # new or replaced archive copies
    kept: int = 0           # archive copy already as full as the store's
    open_days: int = 0      # today's (or a future) file, not copied
    rows: int = 0           # rows in the archive copies written by this run
    low_space: bool = False
    busy: bool = False      # another archive run holds the lock


def _rows(path: Path) -> int:
    """Rows in the three store tables of one day file; a missing table counts 0."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as con:
        present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return sum(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES if t in present)


def _private_dirs(path: Path) -> None:
    """Create ``path`` and any missing parents as 0700 (existing directories are left as they are)."""
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for p in reversed(missing):
        p.mkdir(mode=0o700, exist_ok=True)


def _snapshot(src: Path, tmp: Path) -> None:
    """One consistent single-file copy of ``src`` at ``tmp``, created 0600 (SQLite's journal copies that mode)."""
    tmp.unlink(missing_ok=True)
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    with closing(sqlite3.connect(f"file:{src}?mode=ro", uri=True)) as s, closing(sqlite3.connect(tmp)) as d:
        s.backup(d)
        d.execute("PRAGMA journal_mode = DELETE")   # a single self-contained file: no -wal/-shm siblings


def _cost(src: Path) -> int:
    """Bytes a snapshot of ``src`` may take: the file and its write-ahead log."""
    wal = src.with_name(src.name + "-wal")
    return src.stat().st_size + (wal.stat().st_size if wal.exists() else 0)


def _check_floor(min_free_bytes: float) -> None:
    if not math.isfinite(min_free_bytes) or min_free_bytes < 0:
        raise ValueError("min_free_bytes must be a finite number >= 0")


def archive(raw: Path, dest: Path, today: date | None = None,
            min_free_bytes: float = DEFAULT_MIN_FREE_GB * 1e9) -> ArchiveResult:
    """Copy the closed day files of ``raw`` into ``dest`` by the rules in the module docstring."""
    _check_floor(min_free_bytes)
    today = today or datetime.now(timezone.utc).date()
    result = ArchiveResult()
    closed = []
    for entry in sorted(raw.iterdir()) if raw.is_dir() else ():
        m = DAY_FILE.match(entry.name)
        if not m or not entry.is_file():
            continue
        if date(int(m[1]), int(m[2]), int(m[3])) >= today:
            result.open_days += 1
            continue
        closed.append(entry)
    result.files = len(closed)
    _private_dirs(dest)
    lock_fd = os.open(dest / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result.busy = True
            return result
        # A quick pre-count picks the days that may need a copy; the decision itself is taken on the
        # staged snapshot below, so a store change between the two only ever leads to a skip.
        todo = [src for src in closed
                if not ((dest / src.name).exists() and _rows(dest / src.name) >= _rows(src))]
        result.kept = len(closed) - len(todo)
        if todo and shutil.disk_usage(dest).free - sum(_cost(src) for src in todo) < min_free_bytes:
            result.low_space = True
            return result
        for src in todo:
            out = dest / src.name
            tmp = out.with_name(out.name + ".part")
            _snapshot(src, tmp)
            n = _rows(tmp)
            if out.exists() and _rows(out) >= n:
                tmp.unlink()
                result.kept += 1
                continue
            os.replace(tmp, out)
            result.copied += 1
            result.rows += n
        return result
    finally:
        os.close(lock_fd)


def _floor_gb(text: str) -> float:
    try:
        value = float(text)
        _check_floor(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a finite number >= 0") from None
    return value


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais archive",
                                 description="copy closed raw day files to the long-term archive")
    ap.add_argument("--region", required=True)
    ap.add_argument("--dest", default=os.environ.get(ENV, ""), help=f"archive root (default ${ENV})")
    ap.add_argument("--min-free-gb", type=_floor_gb, default=DEFAULT_MIN_FREE_GB)
    args = ap.parse_args(argv)
    if not args.dest.strip():
        print(f"archive: no destination (--dest or ${ENV})", file=sys.stderr)
        return 2
    result = archive(ais_root(args.region) / "raw", Path(args.dest).expanduser() / args.region,
                     min_free_bytes=args.min_free_gb * 1e9)
    print(json.dumps({"archive": asdict(result)}, sort_keys=True))
    return 1 if result.low_space or result.busy else 0


if __name__ == "__main__":
    sys.exit(main())

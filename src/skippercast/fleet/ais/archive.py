"""``python -m skippercast.fleet.ais archive``: the long-term copy of the raw day files (design.md section 11).

The raw store keeps ``thresholds.retention.raw_days`` of positions, then empties them in place
(store.py). Labelling, reprocessing and the fishing-grounds history need older days, so this command
copies every closed day file (``raw/YYYY-MM-DD.sqlite`` with a day before today, UTC) to an archive
directory outside the store, with SQLite's online backup API (consistent while the listener writes).

Rules:

- a day already in the archive is replaced only when the store's copy holds MORE rows (late
  receipts). The rows are counted in a staged snapshot (``<day>.sqlite.part``) itself, so a store
  file that retention empties (even mid-run) never overwrites a fuller archive copy;
- today's file is never copied (it is still being written);
- nothing is ever deleted from the archive, and the store is only read;
- one run at a time per archive directory (a lock file); a second run copies nothing and exits 1;
- each day is installed on its own (``os.replace`` of a complete snapshot). If a snapshot fails (for
  example the archive disk is full), its ``.part`` is removed, the days already installed stay (each
  is complete), nothing further is copied and the command exits 1 with ``failed``. Free space on the
  archive disk is the caller's check (the scheduled job checks it before it runs this command);
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
import os
from pathlib import Path
import sqlite3
import sys

from .store import DAY_FILE, TABLES, ais_root

__all__ = ["ArchiveResult", "archive", "main"]

ENV = "SKIPPERCAST_FLEET_ARCHIVE"
LOCK = ".archive.lock"


@dataclass
class ArchiveResult:
    files: int = 0          # closed day files in the store
    copied: int = 0         # new or replaced archive copies
    kept: int = 0           # archive copy already as full as the store's
    open_days: int = 0      # today's (or a future) file, not copied
    rows: int = 0           # rows in the archive copies written by this run
    failed: bool = False    # a snapshot failed (e.g. disk full): its .part removed, the run stopped
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


def archive(raw: Path, dest: Path, today: date | None = None) -> ArchiveResult:
    """Copy the closed day files of ``raw`` into ``dest`` by the rules in the module docstring."""
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
        for src in closed:
            out = dest / src.name
            tmp = out.with_name(out.name + ".part")
            try:
                # A quick pre-count skips days the archive already holds in full; the decision itself
                # is taken on the snapshot, so a store change in between only ever leads to a skip.
                if out.exists() and _rows(out) >= _rows(src):
                    result.kept += 1
                    continue
                _snapshot(src, tmp)
                n = _rows(tmp)
                if out.exists() and _rows(out) >= n:
                    result.kept += 1
                    continue
                os.replace(tmp, out)
            except (sqlite3.Error, OSError):
                result.failed = True
                return result
            finally:
                tmp.unlink(missing_ok=True)   # gone after a replace; removed after a skip or a failure
            result.copied += 1
            result.rows += n
        return result
    finally:
        os.close(lock_fd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais archive",
                                 description="copy closed raw day files to the long-term archive")
    ap.add_argument("--region", required=True)
    ap.add_argument("--dest", default=os.environ.get(ENV, ""), help=f"archive root (default ${ENV})")
    args = ap.parse_args(argv)
    if not args.dest.strip():
        print(f"archive: no destination (--dest or ${ENV})", file=sys.stderr)
        return 2
    result = archive(ais_root(args.region) / "raw", Path(args.dest).expanduser() / args.region)
    print(json.dumps({"archive": asdict(result)}, sort_keys=True))
    return 1 if result.failed or result.busy else 0


if __name__ == "__main__":
    sys.exit(main())

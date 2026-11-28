"""``python -m skippercast.fleet.ais archive``: the long-term copy of the raw day files (design.md section 11).

The raw store keeps ``thresholds.retention.raw_days`` of positions, then empties them in place
(store.py). Labelling, reprocessing and the fishing-grounds history need older days, so this command
copies every closed day file (``raw/YYYY-MM-DD.sqlite`` with a day before today, UTC) to an archive
directory outside the store, with SQLite's online backup API (consistent while the listener writes).

Rules:

- a day already in the archive is replaced only when the store's copy holds MORE rows (late
  receipts); a store file that retention has emptied never overwrites a fuller archive copy;
- today's file is never copied (it is still being written);
- nothing is ever deleted from the archive, and the store is only read;
- before copying, the archive's file system must keep ``--min-free-gb`` free after the copy, else the
  command copies nothing and exits 1.

The archive directory comes from ``--dest`` or ``$SKIPPERCAST_FLEET_ARCHIVE`` (``<dest>/<region>/``
holds the day files). Output is one JSON line of counts; no positions, MMSIs or times.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from .store import DAY_FILE, TABLES, ais_root

__all__ = ["ArchiveResult", "archive", "main"]

ENV = "SKIPPERCAST_FLEET_ARCHIVE"
DEFAULT_MIN_FREE_GB = 50.0


@dataclass
class ArchiveResult:
    files: int = 0          # closed day files in the store
    copied: int = 0         # new or replaced archive copies
    kept: int = 0           # archive copy already as full as the store's
    open_days: int = 0      # today's (or a future) file, not copied
    rows: int = 0           # rows in the archive copies written by this run
    low_space: bool = False


def _rows(path: Path) -> int:
    """Rows in the three store tables of one day file; a missing table counts 0."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as con:
        present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return sum(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES if t in present)


def _copy(src: Path, out: Path) -> None:
    tmp = out.with_name(out.name + ".part")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(f"file:{src}?mode=ro", uri=True)) as s, closing(sqlite3.connect(tmp)) as d:
        s.backup(d)
        d.execute("PRAGMA journal_mode = DELETE")   # a single self-contained file: no -wal/-shm siblings
    os.replace(tmp, out)


def archive(raw: Path, dest: Path, today: date | None = None,
            min_free_bytes: float = DEFAULT_MIN_FREE_GB * 1e9) -> ArchiveResult:
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
    dest.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(dest).free - sum(p.stat().st_size for p in closed) < min_free_bytes:
        result.low_space = True
        return result
    for src in closed:
        out = dest / src.name
        n = _rows(src)
        if out.exists() and _rows(out) >= n:
            result.kept += 1
            continue
        _copy(src, out)
        result.copied += 1
        result.rows += n
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais archive",
                                 description="copy closed raw day files to the long-term archive")
    ap.add_argument("--region", default="CA")
    ap.add_argument("--dest", default=os.environ.get(ENV, ""), help=f"archive root (default ${ENV})")
    ap.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB)
    args = ap.parse_args(argv)
    if not args.dest.strip():
        print(f"archive: no destination (--dest or ${ENV})", file=sys.stderr)
        return 2
    result = archive(ais_root(args.region) / "raw", Path(args.dest).expanduser() / args.region,
                     min_free_bytes=args.min_free_gb * 1e9)
    print(json.dumps({"archive": asdict(result)}, sort_keys=True))
    return 1 if result.low_space else 0


if __name__ == "__main__":
    sys.exit(main())

"""MarineCadastre backfill (design.md section 11, D9): ``python -m skippercast.fleet.ais backfill --region CA
--month 2026-06``.

NOAA's daily files arrive 80 to 150 days late, so this fills the months the
listener never heard. ``fleet-ais.yml`` runs it for one month on a dispatch with
``backfill_month``. A run:

1. **targets**: the registry's MMSIs (``process.registry_targets``, the same
   ``GET /api/fleet/jobs/snapshot`` the processor reads), or only ``--mmsi``.
2. **ingest**: every UTC day from the window's first local day to the day after
   its last (a Pacific day ends after UTC midnight) is streamed through
   ``MarineCadastreSource.history``: positions and statics inside the region's
   ``ais.bbox`` of the target MMSIs only. They go to their own store,
   ``<FLEET_VAR>/<region>/ais/backfill/raw/YYYY-MM-DD.sqlite`` (``process.STORES``),
   never the listener's. A day is written to a staging file and moved into place
   only when complete, replacing any earlier copy, so an interrupted or repeated
   run never leaves half a day or a day twice. ``backfill/days/YYYY-MM-DD.json``
   records what a day holds (bbox, MMSIs, counts, ``ingested_at``); a day whose
   record matches this run's bbox and MMSIs is not downloaded again unless
   ``--force``. A day NOAA has not published yet is reported as missing, and a
   cut or corrupt download (``CorruptDay``) or an unreadable file as failed: in
   both cases nothing of that day is stored and the rest go on.
3. **process**: the processor's re-run window (``process.run`` with
   ``source="marinecadastre"``) over the window's local days: the same
   segmentation, classification, events and aggregates, pushed as a
   replace-window of this source only, every trip and event tagged
   ``source=marinecadastre`` and ``rights=noaa-planning-only``
   (``process.SOURCE_RIGHTS``). Map and profile queries for any paid surface
   filter that tag out (D9). Aggregates follow the processor's rules: a trip the
   listener also heard counts once, from the live source
   (``process.SOURCE_PRECEDENCE``, ``aggregate.prefer_sources``), and a season new
   to the processor state never prunes the Worker's older cells unless
   ``--allow-prune`` is given.

Re-running a day or a month gives the same store rows and the same pushed rows.

**Retention** (``apply_retention``): the backfill store follows the live store's
``thresholds.retention`` (design.md section 5), counted from when a day was
ingested rather than from the day itself (NOAA's days are already months old):
a day's positions go ``raw_days`` after its ingest and its statics
``static_days`` after; the file and its record go once both have. Emptying a
day's positions also drops its record, so a later backfill downloads it again.
The scheduled processor run applies it (``process.run``) and so does every
backfill before it ingests. Derived trips, events and aggregates stay, as they
do for the live source.
"""
from __future__ import annotations

import argparse
import calendar
from contextlib import closing
from datetime import date, datetime, time as dtime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from ..config import FleetConfigError, load_region
from ..sinks import worker_base
from . import process
from .sources.base import AisPosition, AisStatic, Bbox, bbox_of
from .sources.marinecadastre import RIGHTS, SOURCE_ID, CorruptDay, DayNotPublished, MalformedFile, \
    MarineCadastreSource
from .events import iso_utc
from .store import AisStore, RetentionLimits, ais_root, retention_limits

__all__ = ["BATCH", "MANIFEST_VERSION", "apply_retention", "backfill", "backfill_store", "ingest_day", "main",
           "retention", "utc_days", "window_ms"]

BATCH = 5_000            # records per store write: bounds memory whatever the day's size
MANIFEST_VERSION = 1

log = logging.getLogger("skippercast.fleet.ais.backfill")


def backfill_store(root: Path) -> AisStore:
    """The backfill's raw store under ``<FLEET_VAR>/<region>/ais`` (``process.STORES``)."""
    return process.STORES[SOURCE_ID](Path(root))


def window_ms(first: date, last: date, tz: str) -> tuple[int, int]:
    """Region-local days ``first`` to ``last`` inclusive as ``[from, to)`` epoch milliseconds."""
    zone = ZoneInfo(tz)
    return tuple(round(datetime.combine(d, dtime(0), zone).timestamp() * 1000) for d in (first, last + timedelta(days=1)))


def utc_days(start_ms: int, end_ms: int) -> list[date]:
    """The UTC days ``[start_ms, end_ms)`` touches."""
    first = datetime.fromtimestamp(start_ms / 1000, timezone.utc).date()
    last = datetime.fromtimestamp((end_ms - 1) / 1000, timezone.utc).date()
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def _write_json(path: Path, document) -> None:
    """Write ``path`` atomically (a temporary file, then a rename). Not ``watch.atomic_write_json``: the processor,
    which runs the backfill's retention, must work without the watch module."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(document, out, sort_keys=True)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _manifest_path(store: AisStore, day: date) -> Path:
    return store.root / "days" / f"{day.isoformat()}.json"


def _wanted(bbox: Bbox, mmsis: Iterable[int]) -> dict:
    return {"bbox": [list(corner) for corner in bbox], "mmsis": sorted(set(mmsis))}


def _ingested(store: AisStore, day: date, wanted: Mapping) -> bool:
    try:
        manifest = json.loads(_manifest_path(store, day).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return False
    return (manifest.get("schema_version") == MANIFEST_VERSION and store.day_path(day).is_file()
            and {k: manifest.get(k) for k in wanted} == dict(wanted))


def ingest_day(source, store: AisStore, day: date, bbox: Bbox, mmsis: Iterable[int], *, force: bool = False,
               batch: int = BATCH, now_ms: int | None = None) -> dict:
    """Stream one UTC day into ``store`` (module docstring, step 2); returns the day's counts.

    Raises what the source raises (``DayNotPublished``, ``CorruptDay``, ``MalformedFile``) with the store as it was.
    """
    mmsis = set(mmsis)
    wanted = _wanted(bbox, mmsis)
    if not force and _ingested(store, day, wanted):
        return {"day": day.isoformat(), "skipped": True}
    staging_root = store.root / "staging" / day.isoformat()
    shutil.rmtree(staging_root, ignore_errors=True)
    staging = AisStore(staging_root)
    counts: dict = {}
    positions: list[AisPosition] = []
    statics: list[AisStatic] = []
    try:
        for record in source.history(day, bbox, mmsis, counts=counts):
            (positions if isinstance(record, AisPosition) else statics).append(record)
            if len(positions) + len(statics) >= batch:
                staging.write(positions=positions, statics=statics)
                positions, statics = [], []
        staging.write(positions=positions, statics=statics)
        with closing(staging.connect(day)) as conn:   # an empty day still gets its (empty) file
            conn.execute("PRAGMA journal_mode=DELETE")   # fold the WAL in, so the move takes one whole file
        target = store.day_path(day)
        target.parent.mkdir(parents=True, exist_ok=True)
        for sidecar in ("-wal", "-shm", "-journal"):
            target.with_name(target.name + sidecar).unlink(missing_ok=True)
        os.replace(staging.day_path(day), target)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    result = {"day": day.isoformat(), **{k: counts.get(k, 0) for k in sorted(counts)}}
    ingested = _now_ms(now_ms)
    _write_json(_manifest_path(store, day), {"schema_version": MANIFEST_VERSION, "source": SOURCE_ID, "rights": RIGHTS,
                                             **wanted, "counts": result, "ingested_ms": ingested,
                                             "ingested_at": iso_utc(ingested)})
    return result


def _now_ms(now_ms: int | None) -> int:
    return round(datetime.now(timezone.utc).timestamp() * 1000) if now_ms is None else now_ms


def _ingested_ms(store: AisStore, day: date) -> int:
    """When the day was ingested: its record's ``ingested_ms``, else the file's modification time."""
    try:
        value = json.loads(_manifest_path(store, day).read_text(encoding="utf-8")).get("ingested_ms")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    except (FileNotFoundError, ValueError, AttributeError):
        pass
    return round(store.day_path(day).stat().st_mtime * 1000)


def apply_retention(store: AisStore, limits: RetentionLimits, now_ms: int) -> dict:
    """Expire backfill days by age since ingest (module docstring); returns what it deleted and emptied."""
    today = datetime.fromtimestamp(now_ms / 1000, timezone.utc).date()
    result: dict = {"deleted": [], "emptied": {}}
    for day in store.days():
        path = store.day_path(day)
        if path.is_symlink() or path.resolve().parent != store.raw_dir.resolve():
            continue
        age = (today - datetime.fromtimestamp(_ingested_ms(store, day) / 1000, timezone.utc).date()).days
        expired = [t for t, limit in (("positions", limits.raw_days), ("statics", limits.static_days)) if age > limit]
        if len(expired) == 2:
            for sidecar in ("-wal", "-shm", "-journal"):
                path.with_name(path.name + sidecar).unlink(missing_ok=True)
            path.unlink()
            _manifest_path(store, day).unlink(missing_ok=True)
            result["deleted"].append(day.isoformat())
            continue
        if not expired or path.stat().st_nlink > 1:
            continue
        emptied = []
        with closing(store.connect(day)) as conn:
            with conn:
                for table in expired:
                    if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                        conn.execute(f"DELETE FROM {table}")
                        emptied.append(table)
            if emptied:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
        if "positions" in expired:
            _manifest_path(store, day).unlink(missing_ok=True)   # positions gone: a later backfill downloads it again
        if emptied:
            result["emptied"][day.isoformat()] = emptied
    return result


def retention(root: Path, region, now_ms: int) -> dict:
    """``apply_retention`` on the backfill store under ``root`` with the region's ``thresholds.retention``: counts."""
    result = apply_retention(backfill_store(root), retention_limits(region), now_ms)
    return {"deleted": len(result["deleted"]), "emptied": len(result["emptied"])}


def backfill(region, worker, *, first: date, last: date, root: Path | None = None, source=None,
             mmsis: Iterable[int] | None = None, force: bool = False, allow_prune: bool = False,
             now_ms: int | None = None, batch: int = BATCH) -> dict:
    """Ingest and process region-local days ``first`` to ``last`` (module docstring)."""
    if last < first:
        raise ValueError("the backfill window ends before it starts")
    root = Path(root) if root is not None else ais_root(region.id)
    store = backfill_store(root)
    source = source if source is not None else MarineCadastreSource(workdir=store.root / "staging")
    targets = process.registry_targets(worker, region.id)
    wanted = set(targets) if mmsis is None else set(mmsis)
    if not wanted:
        raise ValueError("no MMSIs to backfill: the registry lists none and no --mmsi was given")
    window = window_ms(first, last, region.timezone)
    bbox = bbox_of(region.ais)
    now = _now_ms(now_ms)
    counts: dict = {"source": SOURCE_ID, "rights": RIGHTS, "window": [first.isoformat(), last.isoformat()],
                    "mmsis": len(wanted), "retention": retention(root, region, now)}
    days, missing, failed = [], [], []
    for day in utc_days(*window):
        try:
            days.append(ingest_day(source, store, day, bbox, wanted, force=force, batch=batch, now_ms=now))
        except DayNotPublished as error:
            log.warning("%s", error)
            missing.append(day.isoformat())
        except (CorruptDay, MalformedFile) as error:   # one bad day never stops the rest
            log.error("%s: %s", day.isoformat(), error)
            failed.append({"day": day.isoformat(), "error": str(error)[:200]})
    counts.update(days=days, missing=missing, failed=failed)
    if not days:
        counts["processed"] = None   # nothing of this window is in the store
        return counts
    counts["processed"] = process.run(region, worker, root=root, now_ms=now_ms, source=SOURCE_ID, window=window,
                                      mmsis=None if mmsis is None else sorted(wanted), allow_prune=allow_prune)
    return counts


# ---------------------------------------------------------------- command line

def _month(text: str) -> tuple[date, date]:
    try:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    except ValueError:
        raise argparse.ArgumentTypeError("--month takes YYYY-MM") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais backfill",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--region", required=True)
    parser.add_argument("--month", type=_month, help="a whole region-local month, YYYY-MM")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, help="first region-local day")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, help="last region-local day (inclusive)")
    parser.add_argument("--mmsi", type=int, action="append", help="only this MMSI (repeatable)")
    parser.add_argument("--force", action="store_true", help="download and ingest days already in the store again")
    parser.add_argument("--allow-prune", action="store_true",
                        help="let a season new to the processor state replace the Worker's cells for it")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if (args.month is None) == (args.start is None and args.end is None):
        parser.error("give --month, or --from and --to")
    if args.month is None and (args.start is None or args.end is None or args.end < args.start):
        parser.error("--from and --to go together, --to on or after --from")
    first, last = args.month or (args.start, args.end)
    try:
        region = load_region(args.region)
        counts = backfill(region, process.Worker(worker_base()), first=first, last=last, mmsis=args.mmsi,
                          force=args.force, allow_prune=args.allow_prune)
    except (FleetConfigError, process.WorkerError, MalformedFile, ValueError, OSError) as error:
        print(f"fleet ais backfill: {error}", file=sys.stderr)
        return 2
    print(json.dumps(counts, sort_keys=True))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""MarineCadastre backfill (design.md section 11, D9): ``python -m skippercast.fleet.ais backfill --region CA
--month 2026-06``.

NOAA's daily files arrive 80 to 150 days late, so this fills the months the
listener never heard. ``fleet-ais.yml`` runs it for one month on a dispatch with
``backfill_month``. A run:

1. **targets**: the registry's MMSIs (``process.registry_targets``, the same
   ``GET /api/fleet/jobs/snapshot`` the processor reads), or only ``--mmsi``.
2. **ingest**: every UTC day from the window's first local day to the day after
   its last (a Pacific day ends after UTC midnight) is streamed through
   ``MarineCadastreSource.history``: positions inside the region's ``ais.bbox``
   of the target MMSIs, and statics of every vessel in the bbox (for MMSI
   matching, like the listener's). They go to their own store,
   ``<FLEET_VAR>/<region>/ais/backfill/raw/YYYY-MM-DD.sqlite`` (``process.STORES``),
   never the listener's. A day is written to a staging file and moved into place
   only when complete, replacing any earlier copy, so an interrupted or repeated
   run never leaves half a day or a day twice. ``backfill/days/YYYY-MM-DD.json``
   records what a day holds (bbox, MMSIs, counts); a day whose record matches
   this run's bbox and MMSIs is not downloaded again unless ``--force``. A day
   NOAA has not published yet is reported as missing and the rest go on.
3. **process**: the processor's re-run window (``process.run`` with
   ``source="marinecadastre"``) over the window's local days: the same
   segmentation, classification, events and aggregates, pushed as a
   replace-window of this source only, every trip and event tagged
   ``source=marinecadastre`` and ``rights=noaa-planning-only``
   (``process.SOURCE_RIGHTS``). Map and profile queries for any paid surface
   filter that tag out (D9). Aggregates follow the processor's rule: a season new
   to the processor state never prunes the Worker's older cells unless
   ``--allow-prune`` is given.

Re-running a day or a month gives the same store rows and the same pushed rows.
The backfill store has no retention of its own: the scheduled processor applies
``thresholds.retention`` to the listener's store only.
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
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from ..config import FleetConfigError, load_region
from ..sinks import worker_base
from . import process
from .sources.base import AisPosition, AisStatic, Bbox, bbox_of
from .sources.marinecadastre import RIGHTS, SOURCE_ID, DayNotPublished, MalformedFile, MarineCadastreSource
from .store import AisStore, ais_root
from .watch import atomic_write_json

__all__ = ["BATCH", "MANIFEST_VERSION", "backfill", "backfill_store", "ingest_day", "main", "utc_days", "window_ms"]

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
               batch: int = BATCH) -> dict:
    """Stream one UTC day into ``store`` (module docstring, step 2); returns the day's counts."""
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
        for record in source.history(day, bbox, mmsis, counts=counts, all_statics=True):
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
    atomic_write_json(_manifest_path(store, day), {"schema_version": MANIFEST_VERSION, "source": SOURCE_ID,
                                                   "rights": RIGHTS, **wanted, "counts": result})
    return result


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
    days, missing = [], []
    for day in utc_days(*window):
        try:
            days.append(ingest_day(source, store, day, bbox, wanted, force=force, batch=batch))
        except DayNotPublished as error:
            log.warning("%s", error)
            missing.append(day.isoformat())
    counts: dict = {"source": SOURCE_ID, "rights": RIGHTS, "window": [first.isoformat(), last.isoformat()],
                    "mmsis": len(wanted), "days": days, "missing": missing}
    if len(missing) == len(days) + len(missing):
        counts["processed"] = None   # nothing published for this window yet
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

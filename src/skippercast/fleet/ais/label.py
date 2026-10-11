"""Agent labelling for the classifier's validation (N7; design.md section 11 Validation).

``python -m skippercast.fleet.ais label export --region CA --out <dir>`` on the data runner
derives the source store's trips with the processor's own steps (one fix a minute,
``segment.split_trips``, ``classify.classify_trip``; trip ids as ``process.derive`` makes them)
and writes one JSON per trip that ``validation/labels.json`` (the last sync) does not list as
labelled. ``--from``/``--to`` (region-local days, inclusive) keep departures in that window.
Each file holds the trip's id, ports, times, the window labels must fall in, and a minute by
minute summary: reported SOG, course change since the previous fix, distance to the nearest
port geofence, local hour, and ``classifier_hint``, the classifier's current kind. The hint is
for orientation only: labels come from judging the track, never from copying it. ``--out``
resolves under ``<FLEET_VAR>/<region>/ais`` and must stay under FLEET_VAR and out of the
checkout's tracked files.

``label import <file.json>`` checks a proposed-labels file, a list of
``{trip_id, labeller: "agent:<name>", labels: [{started_at, ended_at, label, basis}]}`` (the
admin view's rules, ``server/fleet/admin/labels.ts``, plus each trip's export window), then
posts each trip to ``POST /api/fleet/jobs/labels``, which replaces that agent's labels on the
trip. ``--dry-run`` only checks. Errors and output name entries by position, never by trip id.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta
import json
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from ...paths import repo_root
from ..config import FleetConfigError, load_region
from ..sinks import worker_base
from .classify import classify_trip
from .events import iso_utc, trip_id
from .process import HOUR, STORES, Worker, WorkerError, downsample
from .segment import BASIS, ActivityThresholds, offshore_nm, prepare, split_trips
from .store import ais_root, fleet_var
from .validate import LABELS, LABELS_FILE, TRIP_ID, _ms, _write_json, validation_dir

__all__ = ["COLUMNS", "check", "export", "import_labels", "main", "summary"]

COLUMNS = ("t", "sog_kn", "course_change_deg", "port_nm", "local_hour", "classifier_hint")
HINT = "classifier_hint is the classifier's current kind: a hint, do not copy it as a label"
LABELLER = re.compile(r"^agent:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?Z$")
MAX_LABELS, MAX_BASIS, MIN_LABEL_MS = 200, 500, 60_000   # labels.ts


def _turn(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(abs((b - a + 180.0) % 360.0 - 180.0), 1)


def summary(trip, segments, ports, zone: ZoneInfo) -> list[list]:
    """One row per fix (one a minute) in ``COLUMNS`` order."""
    starts, rows, course = [s.started_at for s in segments], [], None
    for p in trip.positions:
        i = bisect_right(starts, p.ts) - 1
        hint = segments[i].kind if i >= 0 and p.ts < segments[i].ended_at else None
        rows.append([iso_utc(p.ts), None if p.sog is None else round(p.sog, 1), _turn(course, p.cog),
                     round(offshore_nm(ports, p.lat, p.lon), 2), datetime.fromtimestamp(p.ts / 1000, zone).hour, hint])
        course = p.cog if p.cog is not None else course
    return rows


def _out_dir(root: Path, out: str) -> Path:
    path = (root / out).resolve()
    checkout = repo_root().resolve()
    if not path.is_relative_to(fleet_var().resolve()) or (
            path.is_relative_to(checkout) and not path.is_relative_to(checkout / "var")):
        raise ValueError("--out must be under FLEET_VAR and outside the checkout's tracked files")
    return path


def export(region, out: str, *, source: str = "aisstream", window: tuple[int, int] | None = None,
           root: Path | None = None, now_ms: int | None = None) -> dict:
    """Write one summary file per unlabelled trip (module docstring); returns counts."""
    if source not in STORES:
        raise ValueError(f"no raw store for source {source!r}")
    root = Path(root) if root is not None else ais_root(region.id)
    directory = _out_dir(root, out)
    now = round(time.time() * 1000) if now_ms is None else now_ms
    th, zone = ActivityThresholds.from_region(region), ZoneInfo(region.timezone)
    try:
        synced = json.loads((validation_dir(root) / LABELS_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        synced = {}
    labelled = {str(t.get("id")) for t in synced.get("trips") or [] if isinstance(t, dict)}
    start, end = window or (0, now)
    longest = int(max(region.thresholds["activity"]["max_open_trip_hours"].values()) * HOUR)
    by_mmsi = defaultdict(list)
    for p in STORES[source](root).read_positions(start - HOUR, min(end + longest, now)):
        if p.source == source:
            by_mmsi[p.mmsi].append(p)
    counts = {"vessels": len(by_mmsi), "trips": 0, "labelled": 0, "written": 0}
    for mmsi in sorted(by_mmsi):
        for trip in split_trips(downsample(prepare(by_mmsi[mmsi])), region.ports, th, now_ms=now):
            if not start <= trip.departed_at < end:
                continue
            counts["trips"] += 1
            tid = trip_id(mmsi, trip.departed_at, source)
            if tid in labelled:
                counts["labelled"] += 1
                continue
            result = classify_trip(trip, region.ports, th)
            to = trip.returned_at if trip.status != "open" else max((x.ended_at for x in result.segments), default=now)
            _write_json(directory / f"{tid}.json", {
                "trip_id": tid, "region": region.id, "source": source, "status": trip.status,
                "depart_port_id": trip.depart_port_id, "return_port_id": trip.return_port_id,
                "departed_at": iso_utc(trip.departed_at),
                "returned_at": None if trip.status == "open" else iso_utc(trip.returned_at),
                "window": {"from": iso_utc(trip.departed_at), "to": iso_utc(to)}, "basis": BASIS,
                "classifier_version": result.classifier_version, "hint": HINT, "columns": list(COLUMNS),
                "minutes": summary(trip, result.segments, region.ports, zone)})
            counts["written"] += 1
    return counts


def _label(x, lo: int, hi: int) -> tuple[dict | None, str | None]:
    """A proposed label normalised, or the reason it is refused (labels.ts ``addLabel``, plus the export window)."""
    if not isinstance(x, dict):
        return None, "not an object"
    extra = sorted(set(x) - {"started_at", "ended_at", "label", "basis"})
    if extra:
        return None, f"unknown field {extra[0]}"
    if not all(isinstance(x.get(k), str) and ISO.match(x[k]) for k in ("started_at", "ended_at")):
        return None, "started_at and ended_at must be ISO UTC times"
    s, e = _ms(x["started_at"]), _ms(x["ended_at"])
    if e - s < MIN_LABEL_MS:
        return None, "a label covers at least one minute"
    if x.get("label") not in LABELS:
        return None, f"label must be one of {', '.join(LABELS)}"
    basis = x["basis"].strip() if isinstance(x.get("basis"), str) else ""
    if not 2 <= len(basis) <= MAX_BASIS:
        return None, f"basis is required (2 to {MAX_BASIS} characters)"
    if s < lo or e > hi:
        return None, f"the range must fall within the trip ({iso_utc(lo)} to {iso_utc(hi)})"
    return {"started_at": iso_utc(s), "ended_at": iso_utc(e), "label": x["label"], "basis": basis}, None


def check(entries, exports: Path) -> tuple[list[dict], list[str]]:
    """Request bodies for valid entries, and every error by entry position (never by trip id)."""
    bodies, errors, seen = [], [], set()
    for n, entry in enumerate(entries if isinstance(entries, list) else [entries], 1):
        where = f"entry {n}"
        if not isinstance(entry, dict) or set(entry) - {"trip_id", "labeller", "labels"}:
            errors.append(f"{where}: an object with trip_id, labeller and labels only")
            continue
        tid, labeller, labels = entry.get("trip_id"), entry.get("labeller"), entry.get("labels")
        if not isinstance(tid, str) or not TRIP_ID.match(tid) or tid in seen:
            errors.append(f"{where}: trip_id must be 32 hex characters, once per file")
            continue
        seen.add(tid)
        if not isinstance(labeller, str) or not LABELLER.match(labeller):
            errors.append(f"{where}: labeller must be agent:<name>")
            continue
        if not isinstance(labels, list) or not 1 <= len(labels) <= MAX_LABELS:
            errors.append(f"{where}: labels must hold 1 to {MAX_LABELS} labels")
            continue
        try:
            window = json.loads((exports / f"{tid}.json").read_text(encoding="utf-8"))["window"]
            lo, hi = _ms(window["from"]), _ms(window["to"])
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(f"{where}: no export file for this trip in the exports directory")
            continue
        found = len(errors)
        done = []
        for k, x in enumerate(labels, 1):
            label, error = _label(x, lo, hi)
            if error:
                errors.append(f"{where} label {k}: {error}")
            else:
                done.append(label)
        done.sort(key=lambda x: x["started_at"])
        errors += [f"{where}: labels overlap at {b['started_at']}" for a, b in zip(done, done[1:])
                   if b["started_at"] < a["ended_at"]]
        if len(errors) == found:
            bodies.append({"trip_id": tid, "labeller": labeller, "labels": done})
    return bodies, errors


def import_labels(path: Path, worker=None, exports: Path | None = None) -> dict:
    """Check the file; post each trip unless ``worker`` is None (a dry run). Nothing is posted if any entry fails."""
    path = Path(path)
    bodies, errors = check(json.loads(path.read_text(encoding="utf-8")), Path(exports or path.parent))
    if errors:
        raise ValueError("; ".join(errors))
    for body in bodies if worker is not None else ():
        worker.post("labels", body)
    return {"trips": len(bodies), "labels": sum(len(b["labels"]) for b in bodies),
            "posted": 0 if worker is None else len(bodies)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais label", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="write a minute-by-minute summary of each unlabelled trip")
    ex.add_argument("--region", required=True)
    ex.add_argument("--source", choices=sorted(STORES), default="aisstream")
    ex.add_argument("--from", dest="start", type=date.fromisoformat, help="first region-local day of departures")
    ex.add_argument("--to", dest="end", type=date.fromisoformat, help="last region-local day (inclusive)")
    ex.add_argument("--out", required=True, help="directory under <FLEET_VAR>/<region>/ais (or an absolute one under FLEET_VAR)")
    im = sub.add_parser("import", help="check a proposed-labels file and post it to the Worker")
    im.add_argument("file")
    im.add_argument("--exports", help="the export files' directory (default: the proposals file's own)")
    im.add_argument("--dry-run", action="store_true", help="check only; no Worker call")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            counts = import_labels(Path(args.file), None if args.dry_run else Worker(worker_base()), args.exports)
        else:
            if (args.start is None) != (args.end is None) or (args.start and args.end < args.start):
                parser.error("--from and --to go together, --to on or after --from")
            region = load_region(args.region)
            zone = ZoneInfo(region.timezone)
            window = None if args.start is None else tuple(
                round(datetime.combine(d, dtime(0), zone).timestamp() * 1000) for d in (args.start, args.end + timedelta(days=1)))
            counts = export(region, args.out, source=args.source, window=window)
    except (FleetConfigError, WorkerError, ValueError, OSError) as error:
        print(f"fleet ais label: {error}", file=sys.stderr)
        return 2
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

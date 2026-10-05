"""Validation of the AIS classifier against hand labels (design.md section 11 Validation, D10; CF-48).

``python -m skippercast.fleet.ais validate --region CA`` on the runner that holds the raw store:

1. **sync**: ``GET /api/fleet/jobs/labels`` lists the region's labelled trips with
   their labels (made in the admin's labelling view, ``#fleet-trip/<id>``,
   ``server/fleet/admin/labels.ts``). They are written to
   ``<FLEET_VAR>/<region>/ais/validation/labels.json``, and each labelled trip's
   raw positions (its departure minus an hour to its return plus an hour, from
   the store of its source: the listener's, or the MarineCadastre backfill's)
   are copied to ``validation/<trip id>.sqlite``. Retention never reads,
   moves or deletes anything in ``validation/`` (``store.py``), so a labelled
   trip's positions outlive the raw store's ``raw_days``; a copy whose trip has
   no label left is deleted here ("while the label exists", design.md section 5).
   A label whose trip a re-run replaced under another id comes as an orphan: its
   copy is kept and still scored.
   A sync adds whatever the raw store still holds to an existing copy, so a trip
   labelled while it was open is completed on later runs. ``fleet-ais.yml`` runs
   ``--sync-only`` after every scheduled processor run.
2. **score**: each copy is run through the processor's own steps (one fix a
   minute, ``segment.split_trips``, ``classify.classify_trip``) with the region's
   current thresholds, or ``--thresholds`` to re-test others, and compared with
   the labels minute by minute. Every whole minute that starts inside a label is
   one labelled minute; its prediction is the segment covering it, or ``none``
   when no derived trip covers it. Minutes the classifier marks ``gap`` (no
   positions) are reported but not scored.
3. **report**: precision and recall for fishing (drift and troll together: a
   drift minute predicted troll still counts as fishing) and per label, a
   confusion table in minutes, trips scored and missing, labels by labeller kind
   (a person's ``users.id`` or ``agent:<name>``), and the target before any public
   use: at least 30 trips, fishing precision >= 0.8 and recall >= 0.7.
   ``validation/report.json`` and ``report.md`` hold it; the Markdown (printed
   too) carries aggregates only, no MMSI, trip id or labeller id.

``--offline`` skips the sync and scores the copies and ``labels.json`` already
on disk; ``--labeller admin|agent`` scores one kind of labeller's labels, so the
owner can review an agent-labelled set before approving it.

Everything the classifier outputs is inferred from movement, never confirmed
fishing (D10); the report says so. Standard library only.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from contextlib import closing
from dataclasses import astuple, dataclass, fields
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

from ..config import FleetConfigError, load_region
from ..sinks import worker_base
from .classify import FISHING_KINDS, classifier_version, classify_trip
from .events import iso_utc
from .process import HOUR, MINUTE, STORES, Worker, WorkerError, downsample
from .segment import BASIS, ActivityThresholds, prepare, split_trips
from .sources.base import AisPosition
from .store import ais_root

__all__ = ["LABELS", "PREDICTIONS", "TARGET", "Interval", "LabelledTrip", "confusion", "fetch_labels", "main",
           "markdown", "metrics", "predict", "report", "score", "sync", "validation_dir"]

LABELS = ("in-port", "transit", "fishing-drift", "fishing-troll")
PREDICTIONS = LABELS + ("gap", "none")
UNSCORED = ("gap",)
TARGET = {"trips": 30, "fishing_precision": 0.8, "fishing_recall": 0.7}
LEAD_MS = TAIL_MS = HOUR          # positions copied around a trip, so its departure and return are seen in port
LABELS_FILE, REPORT_JSON, REPORT_MD = "labels.json", "report.json", "report.md"
TRIP_ID = re.compile(r"^[0-9a-f]{32}$")
_COLUMNS = tuple(f.name for f in fields(AisPosition))
_COPY_DDL = """CREATE TABLE IF NOT EXISTS positions (
  mmsi INTEGER NOT NULL, ts INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
  sog REAL, cog REAL, heading INTEGER, nav_status INTEGER, msg_type TEXT NOT NULL, source TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  PRIMARY KEY (mmsi, ts, source)) WITHOUT ROWID"""

log = logging.getLogger("skippercast.fleet.ais.validate")


# ---------------------------------------------------------------- scoring (pure)

@dataclass(frozen=True)
class Interval:
    """``[start, end)`` in epoch milliseconds with a label or a predicted kind."""
    start: int
    end: int
    kind: str


def _minutes(interval: Interval) -> range:
    """The whole minutes that start inside the interval."""
    first = -(-interval.start // MINUTE) * MINUTE
    return range(first, interval.end, MINUTE)


def confusion(labels: Iterable[Interval], predictions: Iterable[Interval]) -> dict[str, dict[str, int]]:
    """Minutes by label (rows) and prediction (columns). A minute two labels share counts once, for the earlier one."""
    table = {label: {kind: 0 for kind in PREDICTIONS} for label in LABELS}
    preds = sorted(predictions, key=lambda p: (p.start, p.end))
    starts = [p.start for p in preds]
    seen: set[int] = set()
    for label in sorted(labels, key=lambda x: (x.start, x.end)):
        if label.kind not in table:
            raise ValueError(f"unknown label {label.kind!r}")
        for minute in _minutes(label):
            if minute in seen:
                continue
            seen.add(minute)
            i = bisect_right(starts, minute) - 1   # segments tile their trips, so only the latest start can cover it
            kind = preds[i].kind if i >= 0 and minute < preds[i].end and preds[i].kind in PREDICTIONS else "none"
            table[label.kind][kind] += 1
    return table


def add(total: dict[str, dict[str, int]], part: Mapping[str, Mapping[str, int]]) -> dict[str, dict[str, int]]:
    for label, row in part.items():
        for kind, n in row.items():
            total[label][kind] += n
    return total


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def metrics(table: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    """Precision and recall for fishing and per label from a confusion table; ``gap`` minutes are not scored."""
    scored = [k for k in PREDICTIONS if k not in UNSCORED]
    kinds = {}
    for k in LABELS:
        tp = table[k][k]
        labelled = sum(table[k][p] for p in scored)
        predicted = sum(table[t][k] for t in LABELS)
        kinds[k] = {"labelled_min": labelled, "predicted_min": predicted, "agree_min": tp,
                    "precision": _ratio(tp, predicted), "recall": _ratio(tp, labelled)}
    tp = sum(table[t][p] for t in FISHING_KINDS for p in FISHING_KINDS)
    labelled = sum(table[t][p] for t in FISHING_KINDS for p in scored)
    predicted = sum(table[t][p] for t in LABELS for p in FISHING_KINDS)
    total = sum(sum(row.values()) for row in table.values())
    gap = sum(table[t][p] for t in LABELS for p in UNSCORED)
    return {"minutes": {"labelled": total, "scored": total - gap, "gap_unscored": gap},
            "fishing": {"labelled_min": labelled, "predicted_min": predicted, "agree_min": tp,
                        "precision": _ratio(tp, predicted), "recall": _ratio(tp, labelled)},
            "kinds": kinds, "confusion": {k: dict(v) for k, v in table.items()}}


def score(labels: Iterable[Interval], predictions: Iterable[Interval]) -> dict[str, Any]:
    return metrics(confusion(labels, predictions))


def predict(positions: Iterable[AisPosition], ports: Sequence, thresholds: ActivityThresholds) -> list[Interval]:
    """The processor's segments for one MMSI's positions (one fix a minute, trips, classification)."""
    rows = downsample(prepare(positions))
    out: list[Interval] = []
    for trip in split_trips(rows, ports, thresholds):
        out.extend(Interval(s.started_at, s.ended_at, s.kind) for s in classify_trip(trip, ports, thresholds).segments)
    return out


# ---------------------------------------------------------------- labelled trips and their copies

@dataclass(frozen=True)
class LabelledTrip:
    """A labelled trip from the job route. An orphan's trip row is gone (a re-run replaced it under another id):
    its trip fields are null, and only the copy already on disk, which holds that trip's MMSI and source, is left."""
    id: str
    mmsi: int | None
    source: str | None
    departed_ms: int | None
    returned_ms: int | None
    status: str
    depart_port_id: str | None
    labels: tuple[dict, ...]

    @property
    def orphan(self) -> bool:
        return self.mmsi is None or self.source is None or self.departed_ms is None

    @classmethod
    def from_row(cls, row: Mapping) -> "LabelledTrip":
        if not TRIP_ID.match(str(row.get("id", ""))):
            raise ValueError("a labelled trip needs a 32-hex id")
        orphan = bool(row.get("orphan")) or row.get("mmsi") is None
        return cls(row["id"], None if orphan else int(row["mmsi"]), None if orphan else str(row["source"]),
                   None if orphan else _ms(row["departed_at"]),
                   None if orphan or row.get("returned_at") is None else _ms(row["returned_at"]),
                   str(row.get("status") or ""), row.get("depart_port_id"), tuple(dict(x) for x in row.get("labels") or ()))

    def intervals(self, labeller: str = "all") -> list[Interval]:
        return [Interval(_ms(x["started_at"]), _ms(x["ended_at"]), x["label"]) for x in self.labels
                if labeller == "all" or _labeller_kind(x.get("labeller")) == labeller]


def _ms(iso: str) -> int:
    return round(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)


def _labeller_kind(labeller) -> str:
    return "agent" if str(labeller or "").startswith("agent:") else "admin"


def validation_dir(root: Path) -> Path:
    """``<FLEET_VAR>/<region>/ais/validation``."""
    return Path(root) / "validation"


def fetch_labels(worker, region_id: str) -> list[dict]:
    """Every labelled trip of the region from ``GET /api/fleet/jobs/labels`` (pages by trip id)."""
    trips, cursor = [], ""
    while True:
        page = worker.get("labels", region=region_id, **({"cursor": cursor} if cursor else {}))
        trips.extend(t for t in page.get("trips") or [] if isinstance(t, dict))
        following = page.get("next")
        if not isinstance(following, str) or not TRIP_ID.match(following) or following <= cursor:
            return trips
        cursor = following


def _write_json(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(document, out, sort_keys=True, indent=1)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _copy(path: Path, rows: Iterable[AisPosition]) -> int:
    """Add positions to a trip's copy (a repeated key is ignored); the rows it now holds."""
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute(_COPY_DDL)
            conn.executemany(f"INSERT OR IGNORE INTO positions ({', '.join(_COLUMNS)}) "
                             f"VALUES ({', '.join('?' * len(_COLUMNS))})", (astuple(r) for r in rows))
        return conn.execute("SELECT count(*) FROM positions").fetchone()[0]


def read_copy(path: Path) -> list[AisPosition]:
    """A trip copy's positions by time."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        return [AisPosition(*r) for r in conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM positions ORDER BY ts, source")]


def sync(region, worker, root: Path | None = None, now_ms: int | None = None) -> dict:
    """Fetch the labels, copy labelled trips' raw positions to ``validation/`` and drop copies without a label."""
    root = Path(root) if root is not None else ais_root(region.id)
    now = round(time.time() * 1000) if now_ms is None else now_ms
    rows = fetch_labels(worker, region.id)
    trips = [LabelledTrip.from_row(r) for r in rows]
    directory = validation_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(directory / LABELS_FILE, {"region": region.id, "fetched_at": iso_utc(now), "trips": rows})
    longest = int(max(region.thresholds["activity"]["max_open_trip_hours"].values()) * HOUR)
    counts = {"trips": len(trips), "copied": 0, "positions": 0, "empty": 0, "unsupported": 0, "orphaned": 0, "removed": 0}
    for trip in trips:
        if trip.orphan:   # its labels remain: keep the copy as it is
            counts["orphaned"] += 1
            continue
        if trip.source not in STORES:   # no raw store on this runner for that source
            counts["unsupported"] += 1
            continue
        end = trip.returned_ms if trip.returned_ms is not None else min(now, trip.departed_ms + longest)
        found = list(STORES[trip.source](root).read_positions(trip.departed_ms - LEAD_MS, end + TAIL_MS, [trip.mmsi]))
        held = _copy(directory / f"{trip.id}.sqlite", found)
        counts["copied"] += 1
        counts["positions"] += held
        counts["empty"] += held == 0
    keep = {t.id for t in trips}
    for entry in sorted(directory.iterdir()):
        stem = entry.name.split(".", 1)[0]
        if TRIP_ID.match(stem) and entry.name.startswith(stem + ".sqlite") and stem not in keep \
                and entry.is_file() and not entry.is_symlink():
            entry.unlink()
            counts["removed"] += entry.name == stem + ".sqlite"
    return counts


# ---------------------------------------------------------------- the report

def report(region, root: Path | None = None, *, thresholds: ActivityThresholds | None = None, labeller: str = "all",
           now_ms: int | None = None) -> dict:
    """Score every labelled trip that has a copy (module docstring)."""
    root = Path(root) if root is not None else ais_root(region.id)
    th = thresholds or ActivityThresholds.from_region(region)
    directory = validation_dir(root)
    try:
        document = json.loads((directory / LABELS_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        document = {"trips": []}
    table = {label: {kind: 0 for kind in PREDICTIONS} for label in LABELS}
    scored, missing, by_labeller, ports = 0, 0, Counter(), set()
    for row in document.get("trips") or []:
        trip = LabelledTrip.from_row(row)
        labels = trip.intervals(labeller)
        path = directory / f"{trip.id}.sqlite"
        if not labels or (trip.orphan and not path.is_file()):   # an orphan without a copy here is another region's
            continue
        by_labeller.update(_labeller_kind(x.get("labeller")) for x in trip.labels
                           if labeller == "all" or _labeller_kind(x.get("labeller")) == labeller)
        positions = read_copy(path) if path.is_file() else []
        if not trip.orphan:   # a copy holds one trip's MMSI and source; an orphan's are no longer listed
            positions = [p for p in positions if p.mmsi == trip.mmsi and p.source == trip.source]
        if not positions:
            missing += 1
            continue
        add(table, confusion(labels, predict(positions, region.ports, th)))
        scored += 1
        ports.add(trip.depart_port_id)
    result = metrics(table)
    fishing = result["fishing"]
    met = (scored >= TARGET["trips"] and fishing["precision"] is not None and fishing["recall"] is not None
           and fishing["precision"] >= TARGET["fishing_precision"] and fishing["recall"] >= TARGET["fishing_recall"])
    return {"region": region.id, "computed_at": iso_utc(round(time.time() * 1000) if now_ms is None else now_ms),
            "classifier_version": classifier_version(th), "basis": BASIS, "labeller": labeller,
            "trips": {"scored": scored, "missing": missing, "ports": len(ports - {None})},
            "labels": dict(sorted(by_labeller.items())), **result, "target": {**TARGET, "met": met}}


def _pct(value) -> str:
    return "—" if value is None else f"{value:.3f}"


def markdown(r: Mapping) -> str:
    """The report as Markdown: aggregates only (no MMSI, trip id or labeller id)."""
    f, t = r["fishing"], r["target"]
    lines = [f"## AIS classification validation, {r['region']}", "",
             f"Classifier `{r['classifier_version']}`, scored {r['computed_at']}. Segment kinds are inferred from "
             "movement (speed and track shape), never confirmed fishing; hand labels are the reference.", "",
             f"- Trips scored: {r['trips']['scored']} (target {t['trips']}); without positions: {r['trips']['missing']}; "
             f"departure ports: {r['trips']['ports']}",
             f"- Labels: {', '.join(f'{k} {n}' for k, n in r['labels'].items()) or 'none'}"
             + (f" (only {r['labeller']} labels scored)" if r["labeller"] != "all" else ""),
             f"- Minutes: {r['minutes']['labelled']} labelled, {r['minutes']['scored']} scored, "
             f"{r['minutes']['gap_unscored']} in gaps (not scored)",
             f"- **Fishing precision {_pct(f['precision'])}, recall {_pct(f['recall'])}** "
             f"(target {t['fishing_precision']} and {t['fishing_recall']}): {'met' if t['met'] else 'not met'}", "",
             "| Label | Precision | Recall | Labelled min | Predicted min |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {k} | {_pct(v['precision'])} | {_pct(v['recall'])} | {v['labelled_min']} | {v['predicted_min']} |"
              for k, v in r["kinds"].items()]
    lines += ["", "Confusion (minutes; rows are labels, columns the classifier's output):", "",
              "| Label | " + " | ".join(PREDICTIONS) + " |", "| --- |" + " --- |" * len(PREDICTIONS)]
    lines += [f"| {k} | " + " | ".join(str(row[p]) for p in PREDICTIONS) + " |" for k, row in r["confusion"].items()]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- command line

def _thresholds(region, path: str | None) -> ActivityThresholds | None:
    """The region's activity thresholds with ``path``'s JSON object merged over them (nested one level)."""
    if not path:
        return None
    override = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(override, dict):
        raise ValueError("--thresholds takes a JSON object of activity thresholds")
    base = json.loads(json.dumps(ActivityThresholds.from_region(region).raw))
    for key, value in override.items():
        base[key] = {**base[key], **value} if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return ActivityThresholds.from_mapping(base)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais validate", description=__doc__.splitlines()[0])
    parser.add_argument("--region", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sync-only", action="store_true", help="copy labelled trips' positions; no report")
    mode.add_argument("--offline", action="store_true", help="score the copies on disk; no Worker call")
    parser.add_argument("--labeller", choices=("all", "admin", "agent"), default="all")
    parser.add_argument("--thresholds", help="a JSON file of activity thresholds to re-test instead of the region's")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        region = load_region(args.region)
        root = ais_root(region.id)
        if not args.offline:
            counts = sync(region, Worker(worker_base()), root)
            print(json.dumps({"sync": counts}, sort_keys=True))
            if args.sync_only:
                return 0
        result = report(region, root, thresholds=_thresholds(region, args.thresholds), labeller=args.labeller)
    except (FleetConfigError, WorkerError, ValueError, OSError) as error:
        print(f"fleet ais validate: {error}", file=sys.stderr)
        return 2
    directory = validation_dir(root)
    _write_json(directory / REPORT_JSON, result)
    text = markdown(result)
    (directory / REPORT_MD).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

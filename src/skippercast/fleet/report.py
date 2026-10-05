"""``report``: the charter fleet's aggregate report for one region (design sections 13, 18 and 19; CF-61).

``python -m skippercast.fleet report --region CA [--sink staging|worker] [--open-reviews N] [--d1 TEXT]
[--status-line]``

Reads, as ``coverage-status`` does, the registry from the sink (the staging
database, or ``GET /api/fleet/jobs/snapshot`` and ``/watch`` with the job
token) and, from ``<FLEET_VAR>`` on the runner: the AIS processor's hourly
counters (``<region>/ais/state.sqlite`` ``hours``, the rows it pushes to
``fleet_ais_hours``), the validation report (``ais/validation/report.json``,
CF-48) and the pipeline run directories (``<region>/runs/*``). It reports:

- active boats by port and class with % with an MMSI, % seen in AIS in the last
  30 days (a watched ``fleet_ais_watch`` row heard since then) and completeness,
  and completeness by field group, with the admin coverage view's definitions
  (``server/fleet/admin/coverage.ts``);
- ingestion uptime for 7 and 30 days as the AIS health view counts it
  (``server/fleet/admin/ais-health.ts``: whole UTC hours before the current one,
  up when its counters show a message) and the longest and current run of full
  UTC days (all 24 hours up) in the last 30 days;
- validation precision and recall, run failures in 30 days, the open review
  queue (the staging database holds it; the job API does not, so with
  ``--sink worker`` pass the admin queue's count as ``--open-reviews``) and the
  monthly cost line of section 19 (Places calls from the runs' ``enrich-code``
  reports; D1 usage as ``--d1`` from Cloudflare's usage data; paid items none).

``<FLEET_VAR>/<region>/reports/<date>.json`` and ``.md`` hold it; the Markdown is
printed, or with ``--status-line`` the one line the plan's status log records
(CF-62). Aggregates only: no boat name, contact, link, MMSI or error text.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Iterable, Mapping

from .config import FleetConfigError, FleetRegion, load_region
from .ingest import load_snapshot
from .runs import fleet_var, new_run_id
from .sinks import SinkError, SqliteSink, WorkerSink, worker_base

HOUR, DAY = 3_600_000, 86_400_000
SEEN_DAYS = 30
# server/fleet/admin/coverage.ts FIELD_GROUPS (the resolver's completeness columns, grouped).
FIELD_GROUPS = {
    "identity": ("vessel_class", "waters_json", "port_id", "landing_id"),
    "registry": ("uscg_doc", "state_reg", "hull_id", "call_sign", "mmsi"),
    "specs": ("year_built", "passengers_max", "bunks", "length_ft", "beam_ft", "cruise_kn"),
    "contact": ("website", "booking_url", "booking_platform", "phone_business", "email_business"),
}


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def pct(n: float, d: float) -> float | None:
    """0-100 to one decimal, half up (JavaScript ``Math.round``, as the admin views); None when ``d`` is 0."""
    return math.floor(1000 * n / d + 0.5) / 10 if d else None


def _filled(vessel: Mapping, col: str) -> bool:
    value = vessel.get("waters") if col == "waters_json" and "waters" in vessel else vessel.get(col)
    return value not in (None, "", [], "[]", "null")


def cell(vessels: list[Mapping], seen: set[str]) -> dict:
    boats = len(vessels)
    mmsi, heard = sum(_filled(v, "mmsi") for v in vessels), sum(v["id"] in seen for v in vessels)
    groups = {g: pct(sum(_filled(v, c) for v in vessels for c in cols), boats * len(cols))
              for g, cols in FIELD_GROUPS.items()}
    return {"boats": boats, "mmsi": {"n": mmsi, "pct": pct(mmsi, boats)},
            "seen_30d": {"n": heard, "pct": pct(heard, boats)},
            "completeness": {"mean_pct": pct(sum(float(v.get("completeness") or 0) for v in vessels), boats),
                             "groups": groups}}


def _key(value: str | None) -> tuple:
    return (value is None, value or "")


def coverage(vessels: Iterable[Mapping], watch: Iterable[Mapping], now_ms: int) -> dict:
    """Active boats in total and by port and class; ``seen`` is a watched row heard in the last 30 days."""
    since = iso(now_ms - SEEN_DAYS * DAY)
    seen = {str(w.get("vessel_id")) for w in watch
            if w.get("status", "watched") == "watched" and str(w.get("last_seen_at") or "") >= since}
    active = [v for v in vessels if v.get("status") == "active"]
    ports: dict[str | None, dict[str | None, list]] = {}
    for v in active:
        ports.setdefault(v.get("port_id"), {}).setdefault(v.get("vessel_class"), []).append(v)
    return {"seen_since": since, "totals": cell(active, seen), "ports": [
        {"port_id": port, **cell([v for vs in classes.values() for v in vs], seen),
         "classes": [{"vessel_class": k, **cell(classes[k], seen)} for k in sorted(classes, key=_key)]}
        for port, classes in sorted(ports.items(), key=lambda item: _key(item[0]))]}


def uptime(hours: Mapping[int, int], now_ms: int) -> dict:
    """Uptime over 7 and 30 days of whole UTC hours, and runs of full UTC days in the 30."""
    end = now_ms // HOUR * HOUR
    up = {h for h, messages in hours.items() if messages > 0}

    def window(days: int) -> dict:
        n = sum(end - (i + 1) * HOUR in up for i in range(days * 24))
        return {"pct": pct(n, days * 24), "up_hours": n, "hours": days * 24}

    first = -(-(end - 30 * DAY) // DAY) * DAY
    full = [all(d + i * HOUR in up for i in range(24)) for d in range(first, end - DAY + 1, DAY)]
    longest = current = 0
    for ok in full:
        current = current + 1 if ok else 0
        longest = max(longest, current)
    return {"d7": window(7), "d30": window(30), "full_days": {"longest": longest, "current": current, "days": len(full)},
            "hours_recorded": len(hours)}


def runs_summary(runs: Iterable[Mapping], now_ms: int) -> dict:
    """Pipeline runs created in the last 30 days by status, and their failed steps (no error text)."""
    since = iso(now_ms - 30 * DAY)[:19] + "Z"
    recent = sorted((r for r in runs if str(r.get("created_at") or "") >= since), key=lambda r: r["id"])
    counts = {s: sum(r["status"] == s for r in recent) for s in ("ok", "partial", "failed", "incomplete")}
    return {"since": since, "runs": len(recent), **counts,
            "failed_steps": [{"run_id": r["id"], "step": s} for r in recent for s in r.get("failed_steps", ())]}


def validation(doc: Mapping | None) -> dict | None:
    if not doc:
        return None
    fishing, target = doc.get("fishing") or {}, doc.get("target") or {}
    return {"trips_scored": (doc.get("trips") or {}).get("scored", 0), "precision": fishing.get("precision"),
            "recall": fishing.get("recall"), "target_met": bool(target.get("met")),
            "classifier_version": doc.get("classifier_version"), "computed_at": doc.get("computed_at")}


def cost(runs: Iterable[Mapping], now_ms: int, d1: str | None) -> dict:
    """Section 19's monthly line: Places calls this calendar month (UTC), D1 usage as given, paid items none."""
    month = iso(now_ms)[:7]
    calls = sum(int(r.get("places_calls") or 0) for r in runs if str(r.get("created_at") or "").startswith(month))
    return {"month": month, "places_calls": calls, "d1": d1, "paid_items": "none", "estimate_usd": 0}


def build(region_id: str, *, vessels, watch, hours, runs, validation_doc=None, open_reviews: int | None = None,
          d1: str | None = None, sink: str = "staging", now_ms: int | None = None) -> dict:
    now = round(time.time() * 1000) if now_ms is None else now_ms
    runs = list(runs)
    return {"region": region_id, "generated_at": iso(now), "sink": sink, "seen_days": SEEN_DAYS,
            "groups": {g: list(c) for g, c in FIELD_GROUPS.items()}, **coverage(vessels, watch, now),
            "uptime": uptime(hours, now), "validation": validation(validation_doc), "runs": runs_summary(runs, now),
            "open_reviews": open_reviews, "cost": cost(runs, now, d1)}


# ---------------------------------------------------------------- text

def _p(value) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _n(part: Mapping) -> str:
    return f"{part['n']} ({_p(part['pct'])})"


def _ratio(value) -> str:
    return "—" if value is None else f"{value:.3f}"


def markdown(r: Mapping) -> str:
    t, u, v, runs, c = r["totals"], r["uptime"], r["validation"], r["runs"], r["cost"]
    lines = [f"## Charter fleet report, {r['region']}", "",
             f"Generated {r['generated_at']} from the {r['sink']} registry. Aggregates only. \"Seen\" means heard on "
             f"AIS in the last {r['seen_days']} days; a boat not seen may carry no transponder, and none has to.", "",
             "### Boats by port and class", "",
             "| Port | Class | Boats | MMSI | Seen 30 d | Completeness |", "| --- | --- | --- | --- | --- | --- |"]
    for port in r["ports"]:
        for row, cls in [(port, "all"), *((k, k["vessel_class"] or "unclassified") for k in port["classes"])]:
            lines.append(f"| {port['port_id'] or 'no port'} | {cls} | {row['boats']} | {_n(row['mmsi'])} | "
                         f"{_n(row['seen_30d'])} | {_p(row['completeness']['mean_pct'])} |")
    lines.append(f"| **All ports** | all | {t['boats']} | {_n(t['mmsi'])} | {_n(t['seen_30d'])} | "
                 f"{_p(t['completeness']['mean_pct'])} |")
    lines += ["", "### Field completeness", "", "| Group | Filled |", "| --- | --- |"]
    lines += [f"| {g} | {_p(value)} |" for g, value in t["completeness"]["groups"].items()]
    lines += ["", "### AIS ingestion", "",
              f"- Uptime: 7 days {_p(u['d7']['pct'])} ({u['d7']['up_hours']} of {u['d7']['hours']} hours), "
              f"30 days {_p(u['d30']['pct'])} ({u['d30']['up_hours']} of {u['d30']['hours']} hours)",
              f"- Full UTC days (all 24 hours up) of the last {u['full_days']['days']} complete days: longest run "
              f"{u['full_days']['longest']}, current run {u['full_days']['current']}",
              f"- Hourly counters on this runner: {u['hours_recorded']}", "", "### Classification validation", ""]
    lines.append("- No validation report on this runner." if v is None else
                 f"- {v['trips_scored']} labelled trips scored; fishing precision {_ratio(v['precision'])}, recall "
                 f"{_ratio(v['recall'])}; target {'met' if v['target_met'] else 'not met'} "
                 f"(classifier `{v['classifier_version']}`, scored {v['computed_at']})")
    lines += ["", "### Pipeline runs (30 days)", "",
              f"- {runs['runs']} runs: {runs['ok']} ok, {runs['partial']} partial, {runs['failed']} failed, "
              f"{runs['incomplete']} incomplete"]
    lines += [f"- Failed: run `{f['run_id']}` step `{f['step']}`" for f in runs["failed_steps"]]
    lines += ["", "### Review queue", "", "- Open reviews: " + (
        str(r["open_reviews"]) if r["open_reviews"] is not None else "not counted (pass --open-reviews from the admin queue)"),
              "", f"### Cost, {c['month']}", "",
              f"- Places calls this month: {c['places_calls']}; D1 storage and rows: "
              f"{c['d1'] or 'not recorded (Cloudflare usage data)'}; paid items: {c['paid_items']}; "
              f"estimate ${c['estimate_usd']} (design section 19). Owner confirms against invoices."]
    return "\n".join(lines) + "\n"


def status_line(r: Mapping) -> str:
    """The status-log line CF-62 records: counts and percentages only."""
    t, u, v = r["totals"], r["uptime"], r["validation"]
    ports = "; ".join(f"{p['port_id'] or 'no port'} {p['boats']} ("
                      + ", ".join(f"{k['vessel_class'] or 'unclassified'} {k['boats']}" for k in p["classes"]) + ")"
                      for p in r["ports"])
    checked = ("no validation report" if v is None else
               f"{v['trips_scored']} labelled trips, fishing precision {_ratio(v['precision'])}, recall {_ratio(v['recall'])}")
    reviews = "open reviews not counted" if r["open_reviews"] is None else f"{r['open_reviews']} open reviews"
    return (f"- {r['generated_at'][:10]}: {r['region']} fleet report: {t['boats']} active boats ({ports or 'none'}); "
            f"MMSI {_p(t['mmsi']['pct'])}, seen in 30 days {_p(t['seen_30d']['pct'])}; AIS ingestion "
            f"{u['full_days']['current']} consecutive full days (longest {u['full_days']['longest']}; uptime 7 d "
            f"{_p(u['d7']['pct'])}, 30 d {_p(u['d30']['pct'])}); {checked}; {reviews}.")


# ---------------------------------------------------------------- inputs

def _query(db, sql: str, *args) -> list[dict]:
    cursor = db.execute(sql, args)
    return [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]


def read_hours(path: Path) -> dict[int, int]:
    """The processor's hourly counters (``state.sqlite`` ``hours``): hour start in ms -> messages."""
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        return dict(db.execute("SELECT hour_ms, messages FROM hours").fetchall())


def read_runs(region: FleetRegion, var: Path) -> list[dict]:
    """Each run directory's status, failed steps and Places calls (``enrich-code.json``)."""
    places = {b.id for b in region.sources if b.adapter == "google-places"}
    out = []
    for state_path in sorted((var / region.id / "runs").glob("*/state.json")):
        state, directory = json.loads(state_path.read_text(encoding="utf-8")), state_path.parent
        report = json.loads((directory / "report.json").read_text(encoding="utf-8")) \
            if (directory / "report.json").is_file() else {}
        enrich = json.loads((directory / "enrich-code.json").read_text(encoding="utf-8")) \
            if (directory / "enrich-code.json").is_file() else {}
        calls = sum(int(b.get("searches") or 0) + int(b.get("details") or 0)
                    for k, b in (enrich.get("bindings") or {}).items() if k in places and isinstance(b, dict))
        out.append({"id": state.get("run_id", directory.name), "created_at": state.get("created_at"),
                    "status": report.get("status") if report.get("status") in ("ok", "partial", "failed") else "incomplete",
                    "failed_steps": [s for s, x in (state.get("steps") or {}).items() if x.get("status") == "failed"],
                    "places_calls": calls})
    return out


def collect(region: FleetRegion, sink_kind: str = "staging", var: Path | None = None) -> dict:
    """The registry inputs from the sink and the runner's local inputs, as ``build`` keyword arguments."""
    var = Path(var) if var is not None else fleet_var()
    if sink_kind == "staging":
        path = var / "staging" / f"{region.id}.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        sink = SqliteSink(path, region.id, new_run_id())
        try:
            vessels = load_snapshot(sink, region.id).vessels
            watch = _query(sink.db, "SELECT vessel_id,status,last_seen_at FROM fleet_ais_watch "
                                    "WHERE region=? AND status='watched'", region.id)
            reviews = sink.db.execute("SELECT COUNT(*) FROM fleet_reviews WHERE region=? AND status='open'",
                                      (region.id,)).fetchone()[0]
        finally:
            sink.close()
    else:
        from .ais.match import read_watch_rows
        from .ais.process import Worker
        sink = WorkerSink(worker_base(), region.id, new_run_id(), lambda: 0)
        try:
            vessels = load_snapshot(sink, region.id).vessels
        finally:
            sink.close()
        watch, reviews = read_watch_rows(Worker(worker_base()), region.id, "watched"), None
    ais = var / region.id / "ais"
    validation_path = ais / "validation" / "report.json"
    return {"vessels": vessels, "watch": watch, "open_reviews": reviews, "hours": read_hours(ais / "state.sqlite"),
            "runs": read_runs(region, var), "sink": sink_kind,
            "validation_doc": json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.is_file() else None}


def write(r: Mapping, var: Path) -> tuple[Path, Path]:
    directory = var / r["region"] / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / r["generated_at"][:10]
    stem.with_suffix(".json").write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stem.with_suffix(".md").write_text(markdown(r), encoding="utf-8")
    return stem.with_suffix(".json"), stem.with_suffix(".md")


def main(argv=None, now_ms: int | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet report", description=__doc__.splitlines()[0])
    parser.add_argument("--region", required=True, help="fleet region id, e.g. CA")
    parser.add_argument("--sink", choices=["staging", "worker"], default="staging", help="the registry to report")
    parser.add_argument("--open-reviews", type=int, help="the open review count (the job API does not give it)")
    parser.add_argument("--d1", help="D1 storage and rows this month from Cloudflare's usage data, e.g. '48 MB, 1.2M rows read'")
    parser.add_argument("--status-line", action="store_true", help="print the status-log line instead of the Markdown")
    args = parser.parse_args(argv)
    if args.d1 and re.search(r"://|\b(?:https?|mailto|tel):|www\.|@|\+\d", args.d1, re.I):
        parser.error("--d1 takes usage figures only: no link, address or number with a +")
    var = fleet_var()
    try:
        region = load_region(args.region)
        inputs = collect(region, args.sink, var)
    except (FleetConfigError, SinkError, ValueError, OSError) as error:
        print(f"fleet report: {error}", file=sys.stderr)
        return 2
    if args.open_reviews is not None:
        inputs["open_reviews"] = args.open_reviews
    result = build(region.id, **inputs, d1=args.d1, now_ms=now_ms)
    write(result, var)
    print(status_line(result) if args.status_line else markdown(result), end="\n" if args.status_line else "")
    return 0

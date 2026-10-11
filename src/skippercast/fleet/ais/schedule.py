"""``schedule-correlation``: AIS at-sea days against landing reports (design.md section 11, N4).

A candidate MMSI (stage 2 of ``match.decide``: it broadcasts a registry vessel's
name, alias or call sign, and the vessel holds no registry MMSI) earns this
evidence when the days it was at sea coincide with the days a landing report
named the vessel at its home port:

- an *at-sea day* is a region-local day on which the MMSI sent a position outside
  every port geofence (``match_away`` in the processor state, 30 days);
- a *report day* is the ``date`` of a row of the daily feed's ``reports[]``
  whose ``boat``, normalised as fleet ``name_norm``, is the name or an alias of
  exactly one vessel of the region, and whose ``port`` is a landing name
  (``catalog/advisor/port-aliases.json``) of that vessel's home port; the same
  reading ``server/fleet/pairing.ts`` uses for trip pairing;
- the *matched days* are the at-sea days that are also report days. They
  qualify when there are at least ``thresholds.match.schedule.min_days`` of them
  and the first and last are at least ``min_span_days`` apart, counting both
  ends (5 days over 14 in CA);
- a *rival* is another vessel of the same home port whose own matched days
  (its report days that are also at-sea days) come within ``min_lead`` of this
  vessel's: the schedule cannot tell the two boats apart, so the pair goes to an
  ``mmsi`` review and is never watched. Promotion needs a lead of at least
  ``min_lead`` (3) over every other vessel of the port;
- a *contradiction* is a day the vessel filed a report while the MMSI was in a
  port geofence all day (in port, no position at sea). More than
  ``max_contradictions`` (1) never promotes;
- a watched schedule row lapses to candidate when none of its matched days falls
  in the last ``lapse_days`` (30).

``match.decide`` applies the result; this module holds the pure parts, the feed
loader the processor uses, and ``schedule-precision`` (``python -m
skippercast.fleet.ais schedule-precision``), which measures the method on a
supplied history: registry vessels' own MMSIs are hidden, the matcher runs over
consecutive 30-day windows of the raw store with only schedule evidence able to
promote, and every promotion is scored against the hidden MMSI. It prints
counts only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
import json
import logging
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import name_norm
from ...paths import repo_root

__all__ = ["SCHEDULE", "Rules", "Correlation", "rules", "span_days", "correlate", "landing_ports", "report_days",
           "load_report_days", "precision", "main"]

SCHEDULE = "schedule-correlation"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FEED_TIMEOUT_S = 30
log = logging.getLogger("skippercast.fleet.ais.schedule")


@dataclass(frozen=True)
class Rules:
    min_days: int
    min_span_days: int
    min_lead: int = 3
    max_contradictions: int = 1
    lapse_days: int = 30


def rules(region) -> Rules:
    """``thresholds.match.schedule`` of a fleet region."""
    raw = region.thresholds["match"]["schedule"]
    return Rules(int(raw["min_days"]), int(raw["min_span_days"]), int(raw["min_lead"]),
                 int(raw["max_contradictions"]), int(raw["lapse_days"]))


@dataclass(frozen=True)
class Correlation:
    vessel_id: str
    matched: tuple[str, ...]      # region-local ISO days, sorted
    span_days: int
    qualifies: bool
    rivals: tuple[str, ...]       # other vessels of the home port whose matched days come within min_lead of ours
    contradictions: int = 0       # report days on which the MMSI was in port and not at sea
    contradicted: bool = False    # more of them than max_contradictions

    @property
    def promotes(self) -> bool:
        return self.qualifies and not self.rivals and not self.contradicted


def span_days(days: Iterable[str]) -> int:
    """Days from the first to the last, counting both (0 for none)."""
    ordered = sorted(days)
    if not ordered:
        return 0
    return (date.fromisoformat(ordered[-1]) - date.fromisoformat(ordered[0])).days + 1


def correlate(vessel_id: str, at_sea: Iterable[str], reports: Mapping[str, Iterable[str]],
              port_of: Mapping[str, str | None], rule: Rules, in_port: Iterable[str] = ()) -> Correlation:
    """One MMSI's at-sea days against ``vessel_id``'s report days (module docstring).

    ``in_port`` are the days the MMSI was inside a port geofence. A rival is a
    same-port vessel that shares at least one at-sea day and trails by less than
    ``min_lead``; one that reports only on other days is no rival. Rivals and
    contradictions are judged whenever there is a matched day, so they can undo
    a watched row whose evidence has aged below ``min_days``.
    """
    sea = set(at_sea)
    own = set(reports.get(vessel_id, ()))
    matched = tuple(sorted(sea & own))
    span = span_days(matched)
    qualifies = len(matched) >= rule.min_days and span >= rule.min_span_days
    home = port_of.get(vessel_id)
    rivals: tuple[str, ...] = ()
    if matched and home:
        rivals = tuple(sorted(other for other, days in reports.items()
                              if other != vessel_id and port_of.get(other) == home
                              and (shared := sea & set(days)) and len(matched) - len(shared) < rule.min_lead))
    contradictions = len(own & (set(in_port) - sea))
    return Correlation(vessel_id, matched, span, qualifies, rivals, contradictions,
                       contradictions > rule.max_contradictions)


# ---------------------------------------------------------------- landing reports

def landing_ports(root: Path | None = None) -> dict[str, str]:
    """Landing label (lower case) -> port id, from ``catalog/advisor/port-aliases.json`` ``landing_names``."""
    doc = json.loads(((root or repo_root()) / "catalog/advisor/port-aliases.json").read_text())
    return {name.lower(): port for port, item in doc["ports"].items() for name in item.get("landing_names") or ()}


def report_days(rows: Iterable[Mapping], vessels: Iterable[Mapping], landing: Mapping[str, str]) -> dict[str, set[str]]:
    """Vessel id -> the days a report row named it at its home port (module docstring)."""
    fleet = [v for v in vessels if v.get("status") != "excluded"]
    port_of = {v["id"]: v.get("port_id") for v in fleet}
    names: dict[str, set[str]] = {}
    for v in fleet:
        for norm in [v.get("name_norm") or name_norm(v.get("name") or "")] + \
                [a.get("alias_norm") for a in v.get("aliases") or ()]:
            if norm:
                names.setdefault(norm, set()).add(v["id"])
    out: dict[str, set[str]] = {}
    for r in rows:
        day, boat, label = r.get("date"), r.get("boat"), r.get("port")
        if not (isinstance(day, str) and DATE.match(day) and isinstance(boat, str) and isinstance(label, str)):
            continue
        hits = names.get(name_norm(boat), set())
        if len(hits) != 1:
            continue   # unknown, or a name two vessels share: no evidence for either
        vessel = next(iter(hits))
        if port_of.get(vessel) and landing.get(label.lower()) == port_of[vessel]:
            out.setdefault(vessel, set()).add(day)
    return out


def _fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "SkipperCast-fleet-ais (+https://skippercast.com)"})
    with urlopen(request, timeout=FEED_TIMEOUT_S) as response:
        return json.load(response)


def feed_urls(region, root: Path | None = None) -> list[str]:
    """The daily feeds of the coastal regions the fleet region's ports belong to."""
    base = root or repo_root()
    urls = set()
    for port in region.ports:
        if not port.region:
            continue
        path = base / "regions" / port.region / "region.json"
        if path.exists() and (url := json.loads(path.read_text()).get("daily_feed")):
            urls.add(url)
    return sorted(urls)


def load_report_days(region, vessels: Iterable[Mapping], *, fetch: Callable[[str], Any] = _fetch_json,
                     root: Path | None = None) -> dict[str, set[str]] | None:
    """Report days from the region's daily feeds; None when no feed could be read (no schedule evidence)."""
    urls = feed_urls(region, root)
    rows: list[Mapping] = []
    read = 0
    for url in urls:
        try:
            doc = fetch(url)
        except Exception as error:   # noqa: BLE001 - a feed that fails costs only its evidence
            log.warning("schedule: feed %s unavailable: %s", url, error)
            continue
        if isinstance(doc, Mapping) and isinstance(doc.get("reports"), list):
            rows.extend(r for r in doc["reports"] if isinstance(r, Mapping))
            read += 1
    if not read:
        return None
    return report_days(rows, list(vessels), landing_ports(root))


# ---------------------------------------------------------------- precision on a history window

def precision(region, vessels: list[Mapping], reviews: list[Mapping], windows: Iterable[tuple[Any, ...]],
              reports: Mapping[str, Iterable[str]]) -> dict:
    """Score schedule promotions against registry MMSIs hidden from the matcher.

    ``windows`` yields ``(statics, seen, presence, at_sea, now_ms[, in_port])`` per
    30-day window, as ``match.decide`` takes them; ``in_port`` feeds the
    contradiction rule, as in production. Home-port presence is capped at one
    day, so ``geofence-presence`` cannot fire and every AIS-only promotion is a
    schedule match; a vessel that had no registry MMSI cannot be scored
    (``unverified``).
    """
    from .match import decide   # lazy: match imports this module

    truth = {v["id"]: int(v["mmsi"]) for v in vessels if str(v.get("mmsi") or "").isdigit() and int(v["mmsi"]) > 0}
    hidden = [{**v, "mmsi": None, "pinned": [p for p in v.get("pinned") or () if p != "mmsi"]} for v in vessels]
    counts = {"windows": 0, "schedule_matches": 0, "correct": 0, "false_matches": 0, "unverified": 0,
              "rival_reviews": 0}
    for statics, seen, presence, at_sea, now_ms, *rest in windows:
        counts["windows"] += 1
        capped = {m: {p: min(n, 1) for p, n in ports.items()} for m, ports in presence.items()}
        decision = decide(region, hidden, reviews, statics, seen, capped, {}, now_ms, at_sea=at_sea, reports=reports,
                          in_port=rest[0] if rest else None)
        counts["rival_reviews"] += sum(1 for r in decision.reviews if r["proposal_json"].get("reason") == "schedule-rival")
        for row in decision.rows:
            if row["status"] != "watched" or row["match_method"] != SCHEDULE:
                continue
            counts["schedule_matches"] += 1
            expected = truth.get(row["vessel_id"])
            if expected is None:
                counts["unverified"] += 1
            elif expected == int(row["mmsi"]):
                counts["correct"] += 1
            else:
                counts["false_matches"] += 1
    scored = counts["correct"] + counts["false_matches"]
    counts["precision"] = round(counts["correct"] / scored, 4) if scored else None
    return counts


def _history_windows(region, store, first: date, last: date):
    """``(statics, seen, presence, at_sea, now_ms, in_port)`` for consecutive 30-day windows of ``store``."""
    from .match import SCAN_SLICE_MS, WINDOW_DAYS, MatchState   # lazy: match imports this module

    zone = ZoneInfo(region.timezone)
    start = first
    while start <= last:
        end = min(last, start + timedelta(days=WINDOW_DAYS - 1))
        a = round(datetime.combine(start, dtime(0), zone).timestamp() * 1000)
        b = round(datetime.combine(end + timedelta(days=1), dtime(0), zone).timestamp() * 1000)
        mstate = MatchState(_Memory())
        for k in range(a, b, SCAN_SLICE_MS):
            z = min(b, k + SCAN_SLICE_MS)
            positions = [p for table in ("positions", "discovery") for p in store.read_positions(k, z, table=table)]
            mstate.add(store.read_statics(k, z), positions, region.ports, zone)
        since = start.isoformat()
        yield mstate.statics(), mstate.seen(since), mstate.presence(since), mstate.away(since), b, mstate.in_port(since)
        start = end + timedelta(days=1)


class _Memory:
    """A stand-in for ``process.State``: just the connection ``MatchState`` uses."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)


def _read_reports(path: Path) -> list[Mapping]:
    doc = json.loads(path.read_text())
    rows = doc.get("reports") if isinstance(doc, Mapping) else doc
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a list of report rows or an object with reports[]")
    return [r for r in rows if isinstance(r, Mapping)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais schedule-precision",
                                     description="Precision of schedule-correlation on a history window (counts only).")
    parser.add_argument("--region", required=True)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True, help="first region-local day")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True, help="last region-local day (inclusive)")
    parser.add_argument("--reports", type=Path, required=True,
                        help="JSON: landing report rows {id, date, boat, port}, or an object with reports[]")
    parser.add_argument("--vessels", type=Path,
                        help="JSON list of registry vessels as the snapshot gives them (default: read from the Worker)")
    parser.add_argument("--source", default="marinecadastre", help="raw store to read (default: the backfill store)")
    parser.add_argument("--root", type=Path, help="the region's AIS directory (default: <FLEET_VAR>/<region>/ais)")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--to is before --from")
    from ..config import FleetConfigError, load_region
    from .match import read_snapshot
    from .process import STORES, Worker, WorkerError
    from .store import ais_root
    from ..sinks import worker_base
    try:
        region = load_region(args.region)
        if args.source not in STORES:
            raise ValueError(f"no raw store for source {args.source!r}")
        if args.vessels:
            vessels, reviews = json.loads(args.vessels.read_text()), []
        else:
            vessels, reviews = read_snapshot(Worker(worker_base()), region.id)
        first, last = args.start.isoformat(), args.end.isoformat()
        rows = [r for r in _read_reports(args.reports) if isinstance(r.get("date"), str) and first <= r["date"] <= last]
        days = report_days(rows, vessels, landing_ports())
        store = STORES[args.source](args.root or ais_root(region.id))
        counts = precision(region, vessels, reviews, _history_windows(region, store, args.start, args.end), days)
    except (FleetConfigError, WorkerError, ValueError, OSError) as error:
        print(f"fleet ais schedule-precision: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"region": region.id, "from": first, "to": last, "report_rows": len(rows), **counts},
                     sort_keys=True))
    return 0

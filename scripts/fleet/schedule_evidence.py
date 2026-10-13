#!/usr/bin/env python3
"""Collect private, facts-only charter schedule evidence alongside the existing AIS listener.

This is a deterministic collector. It reads public landing pages with FleetSession's
allowlist/robots/budget checks and the shared pipeline HTTP cache, then reads the
existing AIS processor summaries/raw store in read-only mode. It does not start AIS,
write the registry/watch list, classify fishing, or publish data.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time as monotonic_time
import signal
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from skippercast.fleet.config import FleetRegion, load_region  # noqa: E402
from skippercast.fleet.net import FleetSession, Skipped  # noqa: E402
from skippercast.fleet.adapters.landing_pages import _Page, fleet_entries, parse_html  # noqa: E402
from skippercast.fleet.adapters.teck_reports import teck_client  # noqa: E402

PARSER_VERSION = "fleet-schedule-evidence-v1"
DEFAULT_MAX_PAGES = 20
MAX_INDEX_PAGES_PER_RUN = 16
MAX_AIS_TRIP_ASSESSMENTS_PER_RUN = 150
DEFAULT_DEADLINE_SECONDS = 15 * 60
INDEX_REFRESH_DAYS = 7
AIS_RETENTION_DAYS = 7
AIS_STATIC_LOOKAROUND_HOURS = 48
POSITION_GAP_MINUTES = 10
FISHCOUNTS_URL = "https://www.seaforthlanding.com/fishcounts.php"
FISHCOUNTS_SOURCE_ID = "seaforth-fishcounts"
SEED_BOAT_PATHS = {
    ("www.fishermanslanding.com", "/boats/dolphin.php"),
    ("www.seaforthlanding.com", "/boats/pacifica.php"),
    ("www.pointlomasportfishing.com", "/fleet/wildcard95.php"),
}

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, pages_reviewed INTEGER NOT NULL DEFAULT 0,
  indexes_reviewed INTEGER NOT NULL DEFAULT 0, boats_reviewed INTEGER NOT NULL DEFAULT 0,
  trips_seen INTEGER NOT NULL DEFAULT 0, trip_revisions INTEGER NOT NULL DEFAULT 0,
  ais_assessments INTEGER NOT NULL DEFAULT 0, ais_trips_checked INTEGER NOT NULL DEFAULT 0,
  parser_version TEXT NOT NULL,
  error_class TEXT
);
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY, index_url TEXT NOT NULL, template TEXT NOT NULL,
  rights TEXT NOT NULL, rights_basis TEXT NOT NULL,
  last_index_attempt_at TEXT, last_index_ok_at TEXT, index_sha256 TEXT,
  index_status TEXT NOT NULL DEFAULT 'unknown', listing_revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_pages (
  source_id TEXT NOT NULL, page_url TEXT NOT NULL, boat_name TEXT NOT NULL,
  landing_id TEXT, port_id TEXT, listed_currently INTEGER NOT NULL DEFAULT 1,
  listing_order INTEGER NOT NULL, last_listed_at TEXT NOT NULL,
  last_fetched_at TEXT, page_sha256 TEXT, last_parse_status TEXT NOT NULL DEFAULT 'unknown',
  PRIMARY KEY(source_id,page_url), FOREIGN KEY(source_id) REFERENCES sources(source_id)
);
CREATE INDEX IF NOT EXISTS source_pages_due ON source_pages(listed_currently,last_fetched_at,source_id,listing_order);
CREATE TABLE IF NOT EXISTS source_checks (
  check_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, source_url TEXT NOT NULL,
  final_url TEXT, retrieved_at TEXT NOT NULL, http_status INTEGER,
  content_sha256 TEXT, rights TEXT NOT NULL, rights_basis TEXT NOT NULL,
  interpretation TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_observations (
  trip_id TEXT NOT NULL, revision INTEGER NOT NULL, source_trip_id TEXT NOT NULL,
  source_id TEXT NOT NULL, source_url TEXT NOT NULL, boat_page_url TEXT NOT NULL,
  boat_name TEXT NOT NULL, operator_name TEXT, operator_id TEXT, port_name TEXT, port_id TEXT,
  scheduled_date_local TEXT NOT NULL, timezone TEXT NOT NULL,
  departure_local TEXT, departure_utc TEXT, departure_possible_utc_json TEXT,
  departure_uncertainty TEXT NOT NULL,
  return_local TEXT, return_utc TEXT, return_possible_utc_json TEXT,
  return_uncertainty TEXT NOT NULL,
  duration_hours REAL, trip_type TEXT NOT NULL, target_species_json TEXT,
  schedule_status TEXT NOT NULL, cancellation_evidence TEXT, substitute_vessel TEXT,
  retrieved_at TEXT NOT NULL, parser_version TEXT NOT NULL, rights TEXT NOT NULL,
  rights_basis TEXT NOT NULL, content_sha256 TEXT NOT NULL,
  PRIMARY KEY(trip_id,revision)
);
CREATE INDEX IF NOT EXISTS schedule_date ON schedule_observations(scheduled_date_local,source_id);
CREATE TABLE IF NOT EXISTS schedule_current (
  trip_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, last_seen_at TEXT NOT NULL,
  FOREIGN KEY(trip_id,revision) REFERENCES schedule_observations(trip_id,revision)
);
CREATE TABLE IF NOT EXISTS ais_assessments (
  assessment_id INTEGER PRIMARY KEY, trip_id TEXT NOT NULL, schedule_revision INTEGER NOT NULL,
  assessed_at TEXT NOT NULL, status TEXT NOT NULL, coverage TEXT NOT NULL,
  evidence_json TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
  FOREIGN KEY(trip_id,schedule_revision) REFERENCES schedule_observations(trip_id,revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS ais_assessment_idempotent
  ON ais_assessments(trip_id,schedule_revision,evidence_sha256);
CREATE TABLE IF NOT EXISTS identity_evidence (
  evidence_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, schedule_revision INTEGER NOT NULL,
  candidate_mmsi INTEGER NOT NULL,
  source_class TEXT NOT NULL CHECK(source_class IN ('ais-self-reported','official-register','official-vivs')),
  source_id TEXT NOT NULL, source_record_id TEXT NOT NULL, source_url TEXT,
  field_name TEXT NOT NULL CHECK(field_name IN ('mmsi','vessel_name','call_sign','ship_type',
    'official_number','length_ft','vessel_class','imo','dimensions_ft')),
  field_value TEXT NOT NULL, observed_at_utc TEXT, retrieved_at TEXT NOT NULL,
  parser_version TEXT NOT NULL, rights TEXT NOT NULL, rights_basis TEXT NOT NULL,
  uncertainty TEXT NOT NULL,
  FOREIGN KEY(trip_id,schedule_revision) REFERENCES schedule_observations(trip_id,revision)
);
CREATE INDEX IF NOT EXISTS identity_evidence_trip ON identity_evidence(trip_id,schedule_revision,candidate_mmsi);
CREATE TABLE IF NOT EXISTS ais_current (
  trip_id TEXT NOT NULL, schedule_revision INTEGER NOT NULL, last_checked_at TEXT NOT NULL,
  latest_assessment_id INTEGER NOT NULL,
  PRIMARY KEY(trip_id,schedule_revision),
  FOREIGN KEY(latest_assessment_id) REFERENCES ais_assessments(assessment_id)
);
"""


def stamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(*parts: str) -> str:
    return digest("|".join(parts))[:32]


def name_key(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isascii() and ch.isalnum())


def resolve_local(local: datetime, zone: ZoneInfo) -> tuple[str | None, str | None, str]:
    """Resolve a wall clock without guessing across a DST fold or gap."""
    naive = local.replace(tzinfo=None)
    possibilities: dict[str, datetime] = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        back = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if back == naive:
            utc_value = aware.astimezone(timezone.utc)
            possibilities[utc_value.isoformat(timespec="minutes").replace("+00:00", "Z")] = utc_value
    values = sorted(possibilities)
    if not values:
        return None, None, "nonexistent-local-time"
    if len(values) > 1:
        return None, canonical(values), "ambiguous-local-time"
    return values[0], None, "minute-precision-local-schedule"


def local_midnight_window(day: str, zone: ZoneInfo) -> tuple[datetime, datetime]:
    parsed = date.fromisoformat(day)
    start = datetime.combine(parsed, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(parsed + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return start, end


def trip_projection(departure, candidate, region: FleetRegion, binding, retrieved_at: str) -> dict:
    zone = ZoneInfo(region.timezone)
    date_local = date.fromisoformat(departure.date)
    departure_local = None
    departure_utc = departure_possible = None
    departure_uncertainty = "date-only-schedule"
    if departure.departs_local:
        departure_local = datetime.combine(date_local, time.fromisoformat(departure.departs_local))
        departure_utc, departure_possible, departure_uncertainty = resolve_local(departure_local, zone)
    duration = departure.offering.duration_h
    return_local = return_utc = return_possible = None
    return_uncertainty = "no-return-time-published"
    if departure_local and duration and duration > 0:
        return_local_dt = departure_local + timedelta(hours=duration)
        return_local = return_local_dt.isoformat(timespec="minutes")
        return_utc, return_possible, resolved = resolve_local(return_local_dt, zone)
        return_uncertainty = "derived-from-published-duration; " + resolved
    landing = next((x for x in region.landings if x.id == candidate.landing_hint), None)
    port = next((x for x in region.ports if x.id == candidate.port_hint), None)
    source_url = departure.source_url
    source_trip_id = stable_id(binding.id, candidate.record_id or source_url, departure.date,
                               departure.departs_local or "", departure.offering.name)
    trip_id = source_trip_id
    base = {
        "trip_id": trip_id, "source_trip_id": source_trip_id, "source_id": binding.id,
        "source_url": source_url, "boat_page_url": candidate.record_id or source_url,
        "boat_name": candidate.name, "operator_name": landing.name if landing else None,
        "operator_id": landing.id if landing else binding.id, "port_name": port.name if port else None,
        "port_id": port.id if port else candidate.port_hint,
        "scheduled_date_local": departure.date, "timezone": region.timezone,
        "departure_local": departure_local.isoformat(timespec="minutes") if departure_local else None,
        "departure_utc": departure_utc, "departure_possible_utc_json": departure_possible,
        "departure_uncertainty": departure_uncertainty,
        "return_local": return_local, "return_utc": return_utc,
        "return_possible_utc_json": return_possible, "return_uncertainty": return_uncertainty,
        "duration_hours": duration, "trip_type": departure.offering.trip_type,
        "target_species_json": None, "schedule_status": "listed",
        "cancellation_evidence": None, "substitute_vessel": None,
        "retrieved_at": retrieved_at, "parser_version": PARSER_VERSION,
        "rights": binding.rights,
        "rights_basis": "landing-pages facts-only; internal private use; commercial reuse requires owner/counsel review",
    }
    payload = {key: base[key] for key in base if key not in ("retrieved_at",)}
    base["content_sha256"] = digest(canonical(payload))
    return base


class CachedPageSession:
    """Minimal adapter response over the real FleetSession plus TECK's shared cache client."""
    def __init__(self, net, client, max_pages: int, deadline: float):
        self.net, self.client = net, client
        self.max_pages, self.deadline = max_pages, deadline
        self.pages_reviewed = 0
        self.last_body: dict[str, bytes] = {}
        self.skips = net.skips

    def __getattr__(self, name):
        return getattr(self.net, name)

    def get(self, url: str, **_options):
        if monotonic_time.monotonic() >= self.deadline:
            raise TimeoutError("collector time budget reached")
        if self.pages_reviewed >= self.max_pages:
            skip = Skipped(url, "page-limit", f"{self.max_pages} page reads per run")
            self.skips.append(skip.as_dict())
            raise skip
        self.pages_reviewed += 1
        body = self.client.get(url, as_binary=True)
        receipt = self.client.requests[-1] if self.client.requests else {}
        final = receipt.get("final_url") or url
        self.last_body[final] = body
        return SimpleNamespace(body=body, final_url=final, receipt=receipt)


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    conn = sqlite3.connect(path, timeout=30)
    os.chmod(path, 0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.executescript(SCHEMA)
    return conn


def init_sources(conn: sqlite3.Connection, region: FleetRegion) -> None:
    with conn:
        for binding in region.enabled_sources():
            if binding.adapter != "landing-pages":
                continue
            conn.execute("""INSERT INTO sources(source_id,index_url,template,rights,rights_basis)
                VALUES(?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                index_url=excluded.index_url,template=excluded.template,rights=excluded.rights,
                rights_basis=excluded.rights_basis""",
                (binding.id, binding.params["url"], binding.params["template"], binding.rights,
                 "landing-pages facts-only; internal private use; commercial reuse requires owner/counsel review"))


def refresh_index(conn: sqlite3.Connection, region: FleetRegion, binding, page_session: CachedPageSession,
                  run_dir: Path, now: str) -> tuple[int, int]:
    landing = next((x for x in region.landings if x.id == binding.params.get("landing")), None)
    ctx = SimpleNamespace(region=region, net=page_session, run_dir=run_dir, clock=lambda: now)
    page = _Page(binding, ctx, landing)
    fetched = page.fetch(binding.params["url"])
    if fetched is None:
        with conn:
            conn.execute("UPDATE sources SET last_index_attempt_at=?,index_status='failed' WHERE source_id=?",
                         (now, binding.id))
        return 0, 0
    final_url, root = fetched
    try:
        cards = fleet_entries(root, final_url, binding.params["template"])
    except Exception as error:
        from skippercast.fleet.adapters._html import LayoutError
        if isinstance(error, LayoutError):
            with conn:
                conn.execute("UPDATE sources SET last_index_attempt_at=?,index_status='layout' WHERE source_id=?",
                             (now, binding.id))
            return 0, 0
        raise
    page_sha = hashlib.sha256(page_session.last_body.get(final_url, b"")).hexdigest()
    with conn:
        conn.execute("UPDATE source_pages SET listed_currently=0 WHERE source_id=?", (binding.id,))
        for order, card in enumerate(cards):
            conn.execute("""INSERT INTO source_pages(source_id,page_url,boat_name,landing_id,port_id,
                listed_currently,listing_order,last_listed_at) VALUES(?,?,?,?,?,1,?,?)
                ON CONFLICT(source_id,page_url) DO UPDATE SET boat_name=excluded.boat_name,
                landing_id=excluded.landing_id,port_id=excluded.port_id,listed_currently=1,
                listing_order=excluded.listing_order,last_listed_at=excluded.last_listed_at""",
                (binding.id, card["link"], card["name"], binding.params.get("landing"),
                 landing.port if landing else None, order, now))
        conn.execute("""UPDATE sources SET last_index_attempt_at=?,last_index_ok_at=?,
            index_sha256=?,index_status='ok',listing_revision=listing_revision+1 WHERE source_id=?""",
            (now, now, page_sha, binding.id))
    return 1, len(cards)


def check_fishcounts_source(conn: sqlite3.Connection, page_session: CachedPageSession, now: str) -> bool:
    try:
        response = page_session.get(FISHCOUNTS_URL)
    except (OSError, ValueError, TimeoutError, Skipped):
        with conn:
            conn.execute("""INSERT INTO source_checks(source_id,source_url,retrieved_at,http_status,rights,
                rights_basis,interpretation) VALUES(?,?,?,?,?,?,?)""",
                (FISHCOUNTS_SOURCE_ID,FISHCOUNTS_URL,now,None,"facts-only",
                 "landing-pages facts-only; commercial reuse pending owner/counsel review",
                 "fetch unavailable; no operation claim"))
        return False
    receipt = response.receipt or {}
    with conn:
        conn.execute("""INSERT INTO source_checks(source_id,source_url,final_url,retrieved_at,http_status,
            content_sha256,rights,rights_basis,interpretation) VALUES(?,?,?,?,?,?,?,?,?)""",
            (FISHCOUNTS_SOURCE_ID,FISHCOUNTS_URL,response.final_url,now,receipt.get("http_status"),
             hashlib.sha256(response.body).hexdigest(),"facts-only",
             "landing-pages facts-only; commercial reuse pending owner/counsel review",
             "page reachability only; not evidence of a particular boat trip or fishing"))
    return True


def due_index_sources(conn: sqlite3.Connection, now: datetime) -> list[str]:
    cutoff = stamp(now - timedelta(days=INDEX_REFRESH_DAYS))
    rows = conn.execute("""SELECT source_id FROM sources
        WHERE COALESCE(last_index_ok_at,last_index_attempt_at) IS NULL
           OR COALESCE(last_index_ok_at,last_index_attempt_at) < ?
        ORDER BY CASE WHEN last_index_ok_at IS NULL THEN 0 ELSE 1 END,
                 COALESCE(last_index_ok_at,last_index_attempt_at),source_id""",
        (cutoff,)).fetchall()
    return [row["source_id"] for row in rows]


def _seed_match(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (host, parts.path.lower()) in SEED_BOAT_PATHS


def due_boat_pages(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    # Apply fairness before the per-run limit. These are local inventory
    # records from reviewed pages, so load them all before round-robin selection.
    rows = conn.execute("""SELECT p.* FROM source_pages p
        WHERE p.listed_currently=1
        ORDER BY CASE WHEN p.page_url LIKE '%/boats/dolphin.php' OR p.page_url LIKE '%/boats/pacifica.php'
                     OR p.page_url LIKE '%/fleet/wildcard95.php' THEN 0 ELSE 1 END,
                 CASE WHEN p.last_fetched_at IS NULL THEN 0 ELSE 1 END,
                 p.last_fetched_at,p.source_id,p.listing_order""").fetchall()
    # Round-robin by source so a large fleet page cannot starve other landings.
    seeds = [row for row in rows if _seed_match(row["page_url"])]
    seed_keys = {(row["source_id"], row["page_url"]) for row in seeds}
    remainder = [row for row in rows if (row["source_id"], row["page_url"]) not in seed_keys]
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in remainder:
        grouped.setdefault(row["source_id"], []).append(row)
    fair: list[sqlite3.Row] = []
    while any(grouped.values()):
        for source_id in sorted(grouped):
            if grouped[source_id]:
                fair.append(grouped[source_id].pop(0))
    return (seeds + fair)[:limit]


def explicit_annotations(body: bytes, trip_name: str) -> tuple[str | None, str | None]:
    """Accept only machine-readable status markers; never inspect comments or arbitrary text."""
    root = parse_html(body.decode("utf-8", "replace"))
    wanted = name_key(trip_name)
    for node in root.iter():
        if not node.attrs.get("data-trip-id"):
            continue
        info = node.find(cls="trip-info") or node.find(cls="trip-name")
        if not info or wanted not in name_key(info.text(frozenset({"trip-comments", "trip-icons"}))):
            continue
        classes = node.classes
        status = (node.attrs.get("data-status") or "").strip().lower()
        if status in {"cancelled", "canceled"} or "trip-cancelled" in classes or "trip-canceled" in classes:
            return "explicitly-cancelled", None
        if status in {"substituted", "substitution"} or "trip-substituted" in classes:
            substitute = (node.attrs.get("data-substitute-vessel") or "").strip()
            return "explicitly-substituted", substitute[:120] or None
    return None, None


def record_observation(conn: sqlite3.Connection, row: dict) -> tuple[bool, int]:
    current = conn.execute("SELECT revision FROM schedule_current WHERE trip_id=?", (row["trip_id"],)).fetchone()
    previous = conn.execute("SELECT content_sha256 FROM schedule_observations WHERE trip_id=? ORDER BY revision DESC LIMIT 1",
                             (row["trip_id"],)).fetchone()
    if previous and previous["content_sha256"] == row["content_sha256"]:
        with conn:
            conn.execute("UPDATE schedule_current SET last_seen_at=? WHERE trip_id=?",
                         (row["retrieved_at"], row["trip_id"]))
        return False, int(current["revision"])
    revision = int(current["revision"] + 1) if current else 1
    columns = tuple(row)
    with conn:
        conn.execute(f"INSERT INTO schedule_observations({','.join(columns)},revision) VALUES({','.join('?' for _ in columns)},?)",
                     tuple(row[column] for column in columns) + (revision,))
        conn.execute("""INSERT INTO schedule_current(trip_id,revision,last_seen_at) VALUES(?,?,?)
            ON CONFLICT(trip_id) DO UPDATE SET revision=excluded.revision,last_seen_at=excluded.last_seen_at""",
            (row["trip_id"], revision, row["retrieved_at"]))
    return True, revision


def local_window(row: sqlite3.Row) -> tuple[datetime, datetime, datetime, datetime]:
    zone = ZoneInfo(row["timezone"])
    day_start, day_end = local_midnight_window(row["scheduled_date_local"], zone)
    if row["departure_utc"]:
        dep = datetime.fromisoformat(row["departure_utc"].replace("Z", "+00:00"))
        start = dep - timedelta(hours=2)
        if row["return_utc"]:
            ret = datetime.fromisoformat(row["return_utc"].replace("Z", "+00:00"))
            end = ret + timedelta(hours=2)
        else:
            end = dep + timedelta(hours=2)
        return start, end, day_start, day_end
    return day_start, day_end, day_start, day_end


def read_static_candidates(state_path: Path, boat_name: str, start: datetime, end: datetime) -> tuple[list[dict], str]:
    if not state_path.is_file():
        return [], "ais-state-unavailable"
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    try:
        conn = sqlite3.connect(f"file:{state_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""SELECT mmsi,ts,source,name,call_sign,ship_type,ais_class
                FROM match_statics WHERE ts>=? AND ts<? ORDER BY mmsi,ts""", (start_ms, end_ms)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return [], "ais-state-schema-unavailable"
    target = name_key(boat_name)
    by_mmsi: dict[int, dict] = {}
    for row in rows:
        if name_key(row["name"]) != target:
            continue
        entry = by_mmsi.setdefault(row["mmsi"], {
            "mmsi": row["mmsi"], "ais_names": set(), "call_signs": set(), "ship_types": set(),
            "sources": set(), "first_static_utc": None, "last_static_utc": None, "static_rows": 0,
        })
        entry["ais_names"].add(row["name"] or "")
        if row["call_sign"]:
            entry["call_signs"].add(row["call_sign"])
        if row["ship_type"] is not None:
            entry["ship_types"].add(row["ship_type"])
        entry["sources"].add(row["source"])
        observed = datetime.fromtimestamp(row["ts"] / 1000, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        entry["first_static_utc"] = min(entry["first_static_utc"] or observed, observed)
        entry["last_static_utc"] = max(entry["last_static_utc"] or observed, observed)
        entry["static_rows"] += 1
    candidates = []
    for entry in by_mmsi.values():
        candidates.append({key: sorted(value) if isinstance(value, set) else value
                           for key, value in entry.items()})
    return sorted(candidates, key=lambda item: item["mmsi"]), "ais-match-statics"


def _millis_stamp(value: int | None) -> str | None:
    return (datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            if value is not None else None)


def read_port_presence(state_path: Path, mmsi: int, port_id: str | None, day: str) -> str:
    """Summarize coarse processor port/day evidence, with missing coverage kept unknown."""
    if not port_id or not state_path.is_file():
        return "unknown"
    try:
        conn = sqlite3.connect(f"file:{state_path}?mode=ro", uri=True, timeout=5)
        try:
            observed = conn.execute("SELECT 1 FROM match_presence WHERE mmsi=? AND port_id=? AND day=? LIMIT 1",
                                    (mmsi, port_id, day)).fetchone()
            if observed:
                return "observed-at-home-port-on-schedule-day"
            coverage = conn.execute("SELECT positions FROM match_days WHERE mmsi=? AND day=?",
                                    (mmsi, day)).fetchone()
            return "no-port-presence-recorded" if coverage and coverage[0] else "no-coverage-recorded"
        finally:
            conn.close()
    except sqlite3.Error:
        return "ais-port-summary-unavailable"


def raw_window_summary(fleet_var: Path, region: str, mmsi: int, start: datetime, end: datetime,
                       date_start: datetime, date_end: datetime) -> dict:
    """Summarize readable matching receipt times, never vessel absence or trip proof.

    Completeness covers the existing inclusive one-day-padded scan range. Missing
    buffer/future days remain partial, rather than being called readable empty.
    Coordinates, identities, raw bodies and database error text are not retained.
    """
    raw_dir = fleet_var / region / "ais" / "raw"
    first_day = date_start.date() - timedelta(days=1)
    last_day = date_end.date() + timedelta(days=1)
    expected_days = [(first_day + timedelta(days=i)).isoformat()
                     for i in range((last_day - first_day).days + 1)]
    by_table: dict[str, int] = {"positions": 0, "discovery": 0}
    observations: dict[str, list[tuple[int, int]]] = {"positions": [], "discovery": []}
    readable_days, missing_days, unreadable_days = [], [], []
    store_available = raw_dir.is_dir()
    for day in expected_days:
        path = raw_dir / f"{day}.sqlite"
        if not path.is_file():
            missing_days.append(day)
            continue
        # Commit a day's observations only when both tables were read completely.
        # A later table/query error cannot leave a misleading partial day count.
        day_observations = {"positions": [], "discovery": []}
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
            try:
                for table in ("positions", "discovery"):
                    for ts_ms, received_ms in conn.execute(
                        f"SELECT ts,received_at FROM {table} WHERE mmsi=? AND ts>=? AND ts<? ORDER BY received_at",
                        (mmsi, int(start.timestamp()*1000), int(end.timestamp()*1000))):
                        received_ms, ts_ms = int(received_ms), int(ts_ms)
                        _millis_stamp(received_ms)  # invalid receipt dates hold this day
                        day_observations[table].append((received_ms, ts_ms))
            finally:
                conn.close()
        except (sqlite3.Error, ValueError, TypeError, OverflowError):
            unreadable_days.append(day)
            continue
        readable_days.append(day)
        for table, items in day_observations.items():
            by_table[table] += len(items)
            observations[table].extend(items)
    messages = sum(by_table.values())
    complete = bool(expected_days) and len(readable_days) == len(expected_days)
    if not store_available:
        coverage = "raw-store-unavailable"
    elif complete:
        coverage = "raw-window-readable" if messages else "raw-window-readable-empty"
    elif readable_days:
        coverage = "raw-window-partial"
    elif unreadable_days:
        coverage = "raw-window-unreadable"
    else:
        coverage = "raw-window-not-retained"
    gaps = []
    for table, items in observations.items():
        items.sort()
        for left, right in zip(items, items[1:]):
            gap_ms = right[0] - left[0]
            if gap_ms > POSITION_GAP_MINUTES * 60 * 1000:
                gaps.append({"table": table,
                             "from_received_utc": _millis_stamp(left[0]),
                             "to_received_utc": _millis_stamp(right[0]),
                             "minutes": round(gap_ms/60000, 2)})
    return {"coverage": coverage, "coverage_complete": complete, "messages_complete": complete,
            "expected_days": expected_days, "readable_days": readable_days,
            "missing_days": missing_days, "unreadable_days": unreadable_days,
            "messages": messages, "by_table": by_table,
            "first_received_utc": _millis_stamp(min((x[0] for rows in observations.values() for x in rows), default=None)),
            "last_received_utc": _millis_stamp(max((x[0] for rows in observations.values() for x in rows), default=None)),
            "gaps": gaps}


IDENTITY_FIELD_ALLOWLIST = frozenset({"mmsi", "vessel_name", "call_sign", "ship_type", "official_number",
                                      "length_ft", "vessel_class", "imo", "dimensions_ft"})


def store_ais_identity_evidence(conn: sqlite3.Connection, trip_id: str, revision: int,
                                candidate: dict, retrieved_at: str) -> int:
    """Store only allowlisted identity fields from AIS statics, labelled self-reported."""
    fields = [("mmsi", str(candidate["mmsi"]), None)]
    fields.extend(("vessel_name", value, candidate["first_static_utc"]) for value in candidate["ais_names"])
    fields.extend(("call_sign", value, candidate["first_static_utc"]) for value in candidate["call_signs"])
    fields.extend(("ship_type", str(value), candidate["first_static_utc"]) for value in candidate["ship_types"])
    inserted = 0
    for source_id in candidate["sources"]:
        for field_name, field_value, observed_at in fields:
            if field_name not in IDENTITY_FIELD_ALLOWLIST:
                raise ValueError("identity field is outside the approved facts-only schema")
            record_id = stable_id("ais-static", source_id, str(candidate["mmsi"]), field_name, field_value,
                                  observed_at or "")
            evidence_id = stable_id(trip_id, str(revision), record_id)
            with conn:
                cursor = conn.execute("""INSERT OR IGNORE INTO identity_evidence
                    (evidence_id,trip_id,schedule_revision,candidate_mmsi,source_class,source_id,
                     source_record_id,source_url,field_name,field_value,observed_at_utc,retrieved_at,
                     parser_version,rights,rights_basis,uncertainty)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (evidence_id, trip_id, revision, candidate["mmsi"], "ais-self-reported", source_id,
                     record_id, None, field_name, field_value, observed_at, retrieved_at, PARSER_VERSION,
                     "internal-only", "AIS static message; source terms pending owner/counsel review; private matching only",
                     "AIS static fields are self-reported and do not establish vessel identity"))
            inserted += cursor.rowcount
    return inserted


def assess_ais(conn: sqlite3.Connection, state_path: Path, fleet_var: Path, region: FleetRegion,
               now: datetime) -> tuple[int, int]:
    today = now.astimezone(ZoneInfo(region.timezone)).date()
    cutoff = stamp(now - timedelta(hours=12))
    latest = conn.execute("""SELECT o.* FROM schedule_current c JOIN schedule_observations o
        ON o.trip_id=c.trip_id AND o.revision=c.revision
        LEFT JOIN ais_current a ON a.trip_id=o.trip_id AND a.schedule_revision=o.revision
        WHERE o.scheduled_date_local>=? AND o.scheduled_date_local<=?
          AND COALESCE(a.last_checked_at,'') < ?
        ORDER BY COALESCE(a.last_checked_at,''),o.scheduled_date_local,o.trip_id
        LIMIT ?""",
        ((today - timedelta(days=AIS_RETENTION_DAYS)).isoformat(), (today + timedelta(days=30)).isoformat(),
         cutoff, MAX_AIS_TRIP_ASSESSMENTS_PER_RUN)).fetchall()
    inserted = processed = 0
    for trip in latest:
        start, end, day_start, day_end = local_window(trip)
        look = timedelta(hours=AIS_STATIC_LOOKAROUND_HOURS)
        candidates, source_status = read_static_candidates(state_path, trip["boat_name"], start-look, end+look)
        evidences = []
        for candidate in candidates:
            candidate["reception"] = raw_window_summary(fleet_var, region.id, candidate["mmsi"], start, end,
                                                         day_start, day_end)
            candidate["port_presence"] = read_port_presence(state_path, candidate["mmsi"],
                                                              trip["port_id"], trip["scheduled_date_local"])
            store_ais_identity_evidence(conn, trip["trip_id"], trip["revision"], candidate, stamp(now))
            candidate["evidence_origin"] = "AIS self-reported static fields; no official FCC/PSIX corroboration"
            candidate["interpretation"] = "name-match-candidate-only; not identity approval or proof of trip"
            evidences.append(candidate)
        if not candidates:
            status, coverage = "abstain", source_status
        elif len(candidates) > 1:
            status, coverage = "competing-candidates", source_status
        else:
            status = "candidate-unconfirmed"
            coverage = candidates[0]["reception"]["coverage"]
        evidence = {"status": status, "coverage": coverage, "candidates": evidences,
                    "interpretation": "AIS reception and schedule listings do not prove passengers, departure, or fishing; gaps are preserved."}
        encoded = canonical(evidence)
        hash_value = digest(encoded)
        try:
            with conn:
                cursor = conn.execute("""INSERT OR IGNORE INTO ais_assessments
                    (trip_id,schedule_revision,assessed_at,status,coverage,evidence_json,evidence_sha256)
                    VALUES(?,?,?,?,?,?,?)""",
                    (trip["trip_id"], trip["revision"], stamp(now), status, coverage, encoded, hash_value))
                assessment_id = conn.execute("""SELECT assessment_id FROM ais_assessments
                    WHERE trip_id=? AND schedule_revision=? AND evidence_sha256=?""",
                    (trip["trip_id"], trip["revision"], hash_value)).fetchone()[0]
                conn.execute("""INSERT INTO ais_current(trip_id,schedule_revision,last_checked_at,latest_assessment_id)
                    VALUES(?,?,?,?) ON CONFLICT(trip_id,schedule_revision) DO UPDATE SET
                    last_checked_at=excluded.last_checked_at,latest_assessment_id=excluded.latest_assessment_id""",
                    (trip["trip_id"], trip["revision"], stamp(now), assessment_id))
            inserted += cursor.rowcount
            processed += 1
        except sqlite3.Error:
            raise
    return inserted, processed


def collect_run(region: FleetRegion, db_path: Path, fleet_var: Path, max_pages: int = DEFAULT_MAX_PAGES,
                deadline_seconds: int = DEFAULT_DEADLINE_SECONDS, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    started = stamp(now)
    deadline = monotonic_time.monotonic() + deadline_seconds
    lock_path = db_path.with_suffix(db_path.suffix + ".lock")
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(lock_path.parent, 0o700)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped-locked", "pages_reviewed": 0}
        old_alarm = signal.signal(signal.SIGALRM, lambda _signum, _frame: (_ for _ in ()).throw(TimeoutError("collector deadline reached")))
        signal.setitimer(signal.ITIMER_REAL, deadline_seconds)
        conn = open_database(db_path)
        try:
            init_sources(conn, region)
            with conn:
                conn.execute("INSERT INTO runs(run_id,started_at,status,parser_version) VALUES(?,?,?,?)",
                             (run_id, started, "running", PARSER_VERSION))
            net = FleetSession.for_region(region, budget=600, interval=1.0)
            # Exact existing adapter/client path: FleetSession policy + TECK shared cache.
            ctx = SimpleNamespace(region=region, net=net, run_dir=db_path.parent, clock=lambda: stamp())
            shared_client = teck_client(ctx)
            pages = CachedPageSession(net, shared_client, max_pages, deadline)
            index_count = index_attempts = boat_count = trip_count = revision_count = 0
            bindings = {binding.id: binding for binding in region.enabled_sources()
                        if binding.adapter == "landing-pages"}
            check_fishcounts_source(conn, pages, stamp(now))
            refresh = due_index_sources(conn, now)
            # Seed every current landing index first. On the initial run this discovers links,
            # never claims that a missing/dropped link means a trip was cancelled.
            for source_id in refresh:
                if (pages.pages_reviewed >= max_pages or index_attempts >= MAX_INDEX_PAGES_PER_RUN
                        or monotonic_time.monotonic() >= deadline):
                    break
                binding = bindings.get(source_id)
                if binding is None:
                    continue
                index_attempts += 1
                try:
                    indexes, _ = refresh_index(conn, region, binding, pages, db_path.parent, stamp(now))
                    index_count += indexes
                except (OSError, ValueError, TimeoutError) as error:
                    with conn:
                        conn.execute("UPDATE sources SET last_index_attempt_at=?,index_status=? WHERE source_id=?",
                                     (stamp(now), type(error).__name__[:60], source_id))
            remaining = max_pages - pages.pages_reviewed
            page_rows = due_boat_pages(conn, remaining)
            by_id = {binding.id: binding for binding in region.enabled_sources() if binding.adapter == "landing-pages"}
            for row in page_rows:
                if pages.pages_reviewed >= max_pages or monotonic_time.monotonic() >= deadline:
                    break
                binding = by_id.get(row["source_id"])
                if binding is None:
                    continue
                landing = next((x for x in region.landings if x.id == binding.params.get("landing")), None)
                ctx_page = SimpleNamespace(region=region, net=pages, run_dir=db_path.parent, clock=lambda: stamp())
                page = _Page(binding, ctx_page, landing)
                # The card came from an earlier index fetch. _Page.boat creates
                # its index fact before fetching the boat, so carry that fact's
                # original retrieval time into this fresh parser instance.
                fleet_url = binding.params["url"]
                page.times[fleet_url] = row["last_listed_at"]
                card = {"name": row["boat_name"], "link": row["page_url"], "captains": [], "photo": None}
                before = pages.pages_reviewed
                skip_before = len(pages.skips)
                candidate = page.boat(card, fleet_url)
                if pages.pages_reviewed == before:
                    continue
                boat_count += 1
                raw_body = pages.last_body.get(row["page_url"])
                page_sha = hashlib.sha256(raw_body).hexdigest() if raw_body is not None else None
                page_skips = pages.skips[skip_before:]
                if any(item.get("reason") == "layout" for item in page_skips):
                    parse_status = "layout"
                elif page_skips:
                    parse_status = "fetch-failed"
                else:
                    parse_status = "ok" if candidate.departures else "no-schedule-rows"
                with conn:
                    conn.execute("""UPDATE source_pages SET last_fetched_at=?,page_sha256=?,last_parse_status=?
                        WHERE source_id=? AND page_url=?""",
                        (stamp(now), page_sha, parse_status, row["source_id"], row["page_url"]))
                for departure in candidate.departures:
                    projection = trip_projection(departure, candidate, region, binding,
                                                 departure.retrieved_at or stamp())
                    explicit, substitute = (None, None)
                    if raw_body:
                        explicit, substitute = explicit_annotations(raw_body, departure.offering.name)
                    if explicit:
                        projection["schedule_status"] = explicit
                        projection["cancellation_evidence"] = explicit if explicit == "explicitly-cancelled" else None
                        projection["substitute_vessel"] = substitute
                        projection["content_sha256"] = digest(canonical({key: value for key, value in projection.items()
                                                                          if key != "retrieved_at"}))
                    changed, _revision = record_observation(conn, projection)
                    trip_count += 1
                    revision_count += int(changed)
            state_path = fleet_var / region.id / "ais" / "state.sqlite"
            ais_count, ais_processed = assess_ais(conn, state_path, fleet_var, region, now)
            finished = stamp()
            with conn:
                conn.execute("""UPDATE runs SET finished_at=?,status='ok',pages_reviewed=?,indexes_reviewed=?,
                    boats_reviewed=?,trips_seen=?,trip_revisions=?,ais_assessments=?,ais_trips_checked=? WHERE run_id=?""",
                    (finished, pages.pages_reviewed, index_count, boat_count, trip_count, revision_count,
                     ais_count, ais_processed, run_id))
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return {"status": "ok", "run_id": run_id, "pages_reviewed": pages.pages_reviewed,
                    "indexes_reviewed": index_count, "boat_pages_reviewed": boat_count,
                    "schedule_rows_seen": trip_count, "new_or_changed_schedule_revisions": revision_count,
                    "new_ais_assessments": ais_count, "ais_trips_checked": ais_processed,
                    "skipped_requests": len(net.skips),
                    "parser_version": PARSER_VERSION}
        except BaseException as error:
            with conn:
                conn.execute("UPDATE runs SET finished_at=?,status='failed',pages_reviewed=?,error_class=? WHERE run_id=?",
                             (stamp(), locals().get("pages", SimpleNamespace(pages_reviewed=0)).pages_reviewed,
                              type(error).__name__[:60], run_id))
            raise
        finally:
            conn.close()
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_alarm)


def count_report(db_path: Path) -> dict:
    if not db_path.is_file():
        return {"status": "database-not-created", "schedule_revisions": 0, "current_trips": 0,
                "ais_assessments": 0, "fishcounts_checks": 0}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        latest = conn.execute("""SELECT status,finished_at,pages_reviewed,indexes_reviewed,boats_reviewed,
            trips_seen,trip_revisions,ais_assessments,ais_trips_checked FROM runs ORDER BY started_at DESC LIMIT 1""").fetchone()
        totals = conn.execute("SELECT COUNT(*) FROM schedule_observations").fetchone()[0]
        current = conn.execute("SELECT COUNT(*) FROM schedule_current").fetchone()[0]
        ais = conn.execute("SELECT COUNT(*) FROM ais_assessments").fetchone()[0]
        checks = conn.execute("SELECT COUNT(*) FROM source_checks").fetchone()[0]
        successful_checks = conn.execute("SELECT COUNT(*) FROM source_checks WHERE http_status BETWEEN 200 AND 299").fetchone()[0]
        return {"status": "ok" if latest and latest[0] == "ok" else (latest[0] if latest else "no-runs"),
                "last_finished_at": latest[1] if latest else None,
                "last_run_pages": latest[2] if latest else 0,
                "last_run_indexes": latest[3] if latest else 0,
                "last_run_boat_pages": latest[4] if latest else 0,
                "last_run_schedule_rows": latest[5] if latest else 0,
                "last_run_new_revisions": latest[6] if latest else 0,
                "last_run_new_ais_assessments": latest[7] if latest else 0,
                "last_run_ais_trips_checked": latest[8] if latest else 0,
                "schedule_revisions": totals, "current_trip_records": current,
                "ais_assessments": ais, "fishcounts_checks": checks,
                "successful_fishcounts_checks": successful_checks}
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="CA")
    parser.add_argument("--report", action="store_true", help="read counts only; do not fetch or write")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--deadline-seconds", type=int, default=DEFAULT_DEADLINE_SECONDS)
    args = parser.parse_args(argv)
    if args.region != "CA":
        parser.error("schedule evidence is currently enabled for CA only")
    if not 1 <= args.max_pages <= DEFAULT_MAX_PAGES:
        parser.error(f"--max-pages must be between 1 and {DEFAULT_MAX_PAGES}")
    if not 30 <= args.deadline_seconds <= DEFAULT_DEADLINE_SECONDS:
        parser.error(f"--deadline-seconds must be between 30 and {DEFAULT_DEADLINE_SECONDS}")
    root = Path(os.environ.get("SKIPPERCAST_FLEET_VAR", Path.home() / ".local/share/skippercast/fleet")).expanduser()
    db_path = root / args.region / "schedule-evidence" / "evidence.sqlite3"
    if args.report:
        try:
            print(canonical(count_report(db_path)))
            return 0
        except Exception as error:
            print(canonical({"status": "failed", "error_class": type(error).__name__}), file=sys.stderr)
            return 1
    try:
        region = load_region(args.region, ROOT)
        result = collect_run(region, db_path, root, args.max_pages, args.deadline_seconds)
    except Exception as error:
        print(canonical({"status": "failed", "error_class": type(error).__name__}), file=sys.stderr)
        return 1
    print(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The AIS processor job (design.md section 11): ``python -m skippercast.fleet.ais process --region CA``.

``fleet-ais.yml`` runs it every 30 minutes on the data runner, next to the
listener's raw store. A scheduled run, in order:

1. **heartbeat**: hourly counters for the last hours (``fleet_ais_hours``:
   rows stored per UTC hour, watched rows, distinct MMSIs, longest silence,
   and the listener's reconnects and drops since the previous run) and the
   listener's ``heartbeat.json`` go to ``POST /api/fleet/jobs/heartbeat``
   (``job_state`` ``fleet.ais.<region>.heartbeat``). A missing heartbeat file is
   not sent, so the Worker's health check goes stale.
2. **hooks** (CF-46): ``refresh_watch(ctx)`` writes the listener's
   ``watch.json`` from ``GET /api/fleet/jobs/watch``; ``match(ctx)`` matches
   MMSIs to vessels, pushes watch rows, ``ais`` facts and ``mmsi`` reviews with
   ``POST /api/fleet/jobs/watch``, writes ``watch.json`` again and returns the
   watched MMSIs (``match.py``). Both come from the optional
   ``skippercast.fleet.ais.match`` module; without it the run goes on: there is
   nothing to refresh and the targets are the registry's.
3. **targets**: MMSI -> ``VesselRef``. The registry's MMSIs (``GET
   /api/fleet/jobs/snapshot`` vessels with an ``mmsi``; an MMSI on two vessels
   is skipped), plus the MMSIs ``match`` watches. A registry MMSI keeps its
   registry vessel: ``match`` adds MMSIs, it never reassigns one.
4. **trips**: per target, departures from ``resume`` to ``now - 10 min``,
   from positions read an hour earlier (``resume`` is the departure of the trip
   still open at the last run, else that run's end; the first run looks back
   over ``raw_days``), one fix per
   minute, then ``segment``, ``classify`` and ``events``. Each MMSI's window is
   pushed as a replace-window to ``POST /api/fleet/jobs/activity``: the Worker
   deletes that MMSI's trips, segments and events of this source departing in
   the window and inserts the new set in one D1 batch, so a re-run gives the
   same rows. A window with many trips is split at trip departures.
5. **aggregates** of every season a window touched, from the events this
   processor pushed (mirrored in ``state.sqlite``): only cells whose content
   changed are sent, and cells that vanished are deleted. A season the state has
   never seen is sent whole; the Worker prunes that module's other cells of the
   season only with ``--allow-prune`` or when the state predates the season.
6. **retention** of the raw store (the listener also runs it hourly).
7. **processed**: ``job_state`` ``fleet.ais.<region>.processed``.

``--from DATE --to DATE`` (region-local days, ``--to`` inclusive) re-runs only
steps 3 to 5 for trips departing in that window, reading positions up to the
longest open-trip limit past it, and leaves the resume times alone.

``ais/state.sqlite`` holds the processor's state: resume times per MMSI and
source, hourly counters, the listener counters last seen, the events pushed
and the aggregate cells' digests, and a run log. If it is lost, re-run the
windows still in the raw store (``--from``); events older than the raw store's
``raw_days`` then drop out of the aggregates until a backfill (CF-47).

Rights: aisstream has no published terms, so everything derived from it is
``internal-only``; MarineCadastre is ``noaa-planning-only`` (D9).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
import hashlib
import importlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ... import __version__
from ..config import FleetConfigError, load_region
from ..sinks import worker_base
from . import aggregate
from .classify import classify_trip
from .events import Event, TripContext, build_events, iso_utc, season_of, segment_geometry, segment_id, \
    simplify_tolerance_m, trip_id
from .segment import ActivityThresholds, prepare, split_trips
from .store import AisStore, ais_root, retention_limits

__all__ = ["SOURCE_RIGHTS", "Context", "Derived", "State", "VesselRef", "Worker", "WorkerError", "derive",
           "downsample", "hooks", "hour_counts", "main", "registry_targets", "run"]

MINUTE, HOUR, DAY = 60_000, 3_600_000, 86_400_000
SETTLE_MS = 10 * MINUTE          # positions younger than this wait for the next run
LEAD_MS = HOUR                   # a window starts this long before the resume time, so the departure is seen
HOURS_BACK = 48                  # hourly counters recomputed at most this far back
POST_TRIPS = 50                  # trips per activity request (a window splits at departures beyond it)
POST_BYTES = 768 * 1024          # under the Worker's 1 MB body limit
POST_WINDOWS = 50
CELLS_PER_POST = 500
SOURCE_RIGHTS = {"aisstream": "internal-only", "datalastic": "internal-only", "marinecadastre": "noaa-planning-only"}
# A trip heard by two sources counts once in the aggregates: the live sources win; the backfill fills the rest.
SOURCE_PRECEDENCE = ("aisstream", "datalastic", "marinecadastre")
# Raw store per source under <FLEET_VAR>/<region>/ais: the listener's, and the backfill's (ais/backfill.py).
STORES: dict[str, Callable[[Path], AisStore]] = {"aisstream": AisStore,
                                                 "marinecadastre": lambda root: AisStore(Path(root) / "backfill")}
HOOKS = ("refresh_watch", "match")
HEARTBEAT_FIELDS = ("source", "written_at", "started_at", "last_message_at", "connected", "messages_per_min",
                    "watched_messages_per_min", "vessels", "reconnects", "queue_depth", "watch_size", "git_sha")

log = logging.getLogger("skippercast.fleet.ais.process")


# ---------------------------------------------------------------- the Worker

class WorkerError(RuntimeError):
    pass


class Worker:
    """GET and POST ``/api/fleet/jobs/<path>`` with a GitHub OIDC token; 429, 5xx and transport errors retry.

    Every POST here is idempotent (replace-window, upserts), so a retry after a
    lost response is safe.
    """
    RETRY = (429, 500, 502, 503, 504)

    def __init__(self, base: str, *, opener=urlopen, token_source: Callable[[], str] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 attempts: int = 5):
        parts = urlsplit(base)
        if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
            raise WorkerError(f"the Worker base must be https: {base}")
        self.base = base.rstrip("/")
        self.audience = self.base + "/api/fleet/jobs"
        self.opener, self.sleep, self.clock, self.attempts = opener, sleep, clock, attempts
        self.token_source = token_source or self._github_token
        self.user_agent = f"SkipperCast-fleet-ais/{__version__} (+{self.base})"
        self._token, self._at = None, -1e9

    def _github_token(self) -> str:
        url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&" + urlencode({"audience": self.audience})
        request = Request(url, headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"],
                                        "User-Agent": self.user_agent})
        with self.opener(request, timeout=20) as response:
            return json.load(response)["value"]

    def token(self) -> str:
        if self._token is None or self.clock() - self._at > 240:   # tokens live about 5 minutes
            self._token, self._at = self.token_source(), self.clock()
        return self._token

    def request(self, method: str, path: str, body: Mapping | None = None, params: Mapping | None = None) -> dict:
        url = f"{self.audience}/{path}" + ("?" + urlencode(params) if params else "")
        data = None if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        for attempt in range(1, self.attempts + 1):
            headers = {"Authorization": "Bearer " + self.token(), "Accept": "application/json",
                       "User-Agent": self.user_agent}
            if data is not None:
                headers["Content-Type"] = "application/json"
            try:
                with self.opener(Request(url, data=data, method=method, headers=headers), timeout=60) as response:
                    return json.load(response)
            except HTTPError as error:
                detail = (error.read() or b"")[:300].decode(errors="replace")
                if error.code not in self.RETRY or attempt == self.attempts:
                    raise WorkerError(f"{method} {path}: HTTP {error.code} {detail}".strip()) from None
            except OSError as error:
                if attempt == self.attempts:
                    raise WorkerError(f"{method} {path}: {type(error).__name__}: {error}") from None
            self.sleep(min(60.0, 2.0 ** attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Mapping) -> dict:
        return self.request("POST", path, body=body)


# ---------------------------------------------------------------- state

_STATE_DDL = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cursors (mmsi INTEGER NOT NULL, source TEXT NOT NULL, resume_ms INTEGER NOT NULL,
  PRIMARY KEY (mmsi, source));
CREATE TABLE IF NOT EXISTS hours (hour_ms INTEGER PRIMARY KEY, messages INTEGER NOT NULL, watched_messages INTEGER NOT NULL,
  vessels INTEGER NOT NULL, max_gap_s INTEGER NOT NULL, reconnects INTEGER NOT NULL DEFAULT 0, dropped INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, mmsi INTEGER NOT NULL, source TEXT NOT NULL,
  departed_ms INTEGER NOT NULL, season TEXT NOT NULL, row TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_window ON events (mmsi, source, departed_ms);
CREATE INDEX IF NOT EXISTS events_season ON events (season);
CREATE TABLE IF NOT EXISTS cells (id TEXT PRIMARY KEY, season TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, counts TEXT);
"""


class State:
    """``<FLEET_VAR>/<region>/ais/state.sqlite`` (module docstring)."""

    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.executescript(_STATE_DDL)

    def close(self) -> None:
        self.db.close()

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def put(self, key: str, value) -> None:
        self.db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, sort_keys=True)))

    def resume(self, mmsi: int, source: str) -> int | None:
        row = self.db.execute("SELECT resume_ms FROM cursors WHERE mmsi=? AND source=?", (mmsi, source)).fetchone()
        return None if row is None else row[0]

    def set_resume(self, mmsi: int, source: str, ms: int) -> None:
        self.db.execute("INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(mmsi,source) DO UPDATE SET resume_ms=excluded.resume_ms",
                        (mmsi, source, ms))

    def set_hour(self, hour_ms: int, counts: Mapping[str, int]) -> None:
        self.db.execute("""INSERT INTO hours(hour_ms,messages,watched_messages,vessels,max_gap_s) VALUES(?,?,?,?,?)
          ON CONFLICT(hour_ms) DO UPDATE SET messages=excluded.messages, watched_messages=excluded.watched_messages,
          vessels=excluded.vessels, max_gap_s=excluded.max_gap_s""",
                        (hour_ms, counts["messages"], counts["watched_messages"], counts["vessels"], counts["max_gap_s"]))

    def add_listener_counts(self, hour_ms: int, reconnects: int, dropped: int) -> None:
        self.db.execute("UPDATE hours SET reconnects=reconnects+?, dropped=dropped+? WHERE hour_ms=?",
                        (reconnects, dropped, hour_ms))

    def hours(self, first_ms: int) -> list[dict]:
        rows = self.db.execute("SELECT hour_ms,messages,watched_messages,vessels,reconnects,max_gap_s,dropped FROM hours "
                               "WHERE hour_ms>=? ORDER BY hour_ms", (first_ms,)).fetchall()
        keys = ("messages", "watched_messages", "vessels", "reconnects", "max_gap_s", "dropped")
        return [{"hour": iso_utc(r[0]), **dict(zip(keys, r[1:]))} for r in rows]

    def messages_since(self, first_ms: int) -> int:
        return self.db.execute("SELECT COALESCE(SUM(messages),0) FROM hours WHERE hour_ms>=?", (first_ms,)).fetchone()[0]

    def replace_events(self, source: str, windows: Iterable[tuple[int, int, int]], events: Iterable[Event],
                       departures: Mapping[str, int]) -> None:
        """Mirror a pushed replace-window: (mmsi, from, to) windows, then the window's events."""
        with self.db:
            self.db.execute("BEGIN")
            for mmsi, start, end in windows:
                self.db.execute("DELETE FROM events WHERE mmsi=? AND source=? AND departed_ms>=? AND departed_ms<?",
                                (mmsi, source, start, end))
            self.db.executemany("INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?)", [
                (e.id, departures[e.trip_id][0], source, departures[e.trip_id][1], e.season,
                 json.dumps(e.as_row(), sort_keys=True)) for e in events])

    def season_events(self, season: str) -> list[Event]:
        return [Event.from_row(json.loads(r[0])) for r in
                self.db.execute("SELECT row FROM events WHERE season=? ORDER BY id", (season,))]

    def cells(self, season: str) -> dict[str, str]:
        return dict(self.db.execute("SELECT id, digest FROM cells WHERE season=?", (season,)).fetchall())

    def update_cells(self, season: str, digests: Mapping[str, str], deleted: Iterable[str], full: bool) -> None:
        with self.db:
            self.db.execute("BEGIN")
            if full:
                self.db.execute("DELETE FROM cells WHERE season=?", (season,))
            self.db.executemany("DELETE FROM cells WHERE id=?", [(i,) for i in deleted])
            self.db.executemany("INSERT OR REPLACE INTO cells VALUES(?,?,?)", [(i, season, d) for i, d in digests.items()])

    def log_run(self, run_id: str, started_at: str, finished_at: str | None, counts: Mapping | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)",
                        (run_id, started_at, finished_at, None if counts is None else json.dumps(counts, sort_keys=True)))


# ---------------------------------------------------------------- derivation (pure)

@dataclass(frozen=True)
class VesselRef:
    """The registry vessel an MMSI belongs to, and what its trips and events inherit."""
    vessel_id: str
    vessel_class: str | None = None
    port_id: str | None = None


@dataclass
class Derived:
    """One MMSI's derived rows for one window ``[window_from, window_to)`` of departures (epoch ms)."""
    mmsi: int
    window_from: int
    window_to: int
    trips: list[dict]
    segments: list[dict]
    events: list[Event]
    resume_ms: int


def downsample(rows: Iterable) -> list:
    """The first fix of each UTC minute (``rows`` sorted by time, as ``segment.prepare`` returns them)."""
    out, minute = [], None
    for p in rows:
        if p.ts // MINUTE != minute:
            out.append(p)
            minute = p.ts // MINUTE
    return out


def derive(positions: Iterable, mmsi: int, ref: VesselRef, region, *, source: str, window_from: int,
           window_to: int, now_ms: int, computed_at: str) -> Derived:
    """Trips departing in ``[window_from, window_to)``, their segments and events. Pure."""
    th = ActivityThresholds.from_region(region)
    tolerance = simplify_tolerance_m(th)
    rights, zone = SOURCE_RIGHTS[source], ZoneInfo(region.timezone)
    rows = downsample(prepare(p for p in positions if p.mmsi == mmsi and p.source == source))
    trips, segments, events, resume = [], [], [], window_to
    for trip in split_trips(rows, region.ports, th, vessel_class=ref.vessel_class, now_ms=now_ms):
        if not window_from <= trip.departed_at < window_to:
            continue
        if trip.status == "open":
            resume = min(resume, trip.departed_at)
        result = classify_trip(trip, region.ports, th)
        tid = trip_id(mmsi, trip.departed_at, source)
        season, part = season_of(trip.departed_at, region.timezone, region.seasons)
        trips.append({
            "id": tid, "region": region.id, "vessel_id": ref.vessel_id, "mmsi": str(mmsi),
            "depart_port_id": trip.depart_port_id, "return_port_id": trip.return_port_id,
            "departed_at": iso_utc(trip.departed_at),
            "returned_at": None if trip.status == "open" else iso_utc(trip.returned_at),
            "local_date": datetime.fromtimestamp(trip.departed_at / 1000, zone).date().isoformat(),
            "season": season, "season_part": part, "status": trip.status, "trip_type_inferred": None,
            "distance_nm": round(trip.distance_nm, 3), "max_offshore_nm": round(trip.max_offshore_nm, 3),
            "fishing_min": round(result.fishing_min), "positions_n": len(trip.positions),
            "gap_min": round(result.gap_min), "source": source, "rights": rights,
            "classifier_version": result.classifier_version, "computed_at": computed_at})
        for seg in result.segments:
            segments.append({
                "id": segment_id(tid, seg.seq), "trip_id": tid, "seq": seg.seq, "kind": seg.kind,
                "started_at": iso_utc(seg.started_at), "ended_at": iso_utc(seg.ended_at),
                "geometry": segment_geometry(seg, tolerance), "points_n": seg.points_n, "mean_sog": seg.mean_sog,
                "straightness": seg.straightness, "heading_var": seg.heading_var})
        context = TripContext(tid, ref.vessel_id, region.id, source, rights, season, part,
                              trip.depart_port_id or ref.port_id, ref.vessel_class, None)
        events.extend(build_events(result, region.ports, context))
    return Derived(mmsi, window_from, window_to, trips, segments, events, resume)


def _size(value) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def _units(d: Derived, limit: int = POST_TRIPS) -> list[dict]:
    """Replace-window units for one MMSI: sub-windows split at trip departures, each under the request limits."""
    def unit(start, end, trips):
        ids = {t["id"] for t in trips}
        segments = [s for s in d.segments if s["trip_id"] in ids]
        events = [e for e in d.events if e.trip_id in ids]
        return {"window": (d.mmsi, start, end), "trips": trips, "segments": segments, "events": events,
                "bytes": _size([trips, segments, [e.as_row() for e in events]])}

    def split(start, end, trips):
        part = unit(start, end, trips)
        if len(trips) > 1 and (len(trips) > limit or part["bytes"] > POST_BYTES):
            middle = len(trips) // 2
            cut = _ms(trips[middle]["departed_at"])
            return split(start, cut, trips[:middle]) + split(cut, end, trips[middle:])
        return [part]

    return split(d.window_from, d.window_to, d.trips)


def _ms(iso: str) -> int:
    return round(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def hour_counts(store: AisStore, hour_ms: int, now_ms: int) -> dict[str, int]:
    """Rows the store holds for one UTC hour: all, watched (``positions``), distinct MMSIs and the longest silence."""
    end = hour_ms + HOUR
    stamps, vessels, watched = [], set(), 0
    for table in ("positions", "discovery"):
        for p in store.read_positions(hour_ms, end, table=table):
            stamps.append(p.ts)
            vessels.add(p.mmsi)
            watched += table == "positions"
    for s in store.read_statics(hour_ms, end):
        stamps.append(s.ts)
        vessels.add(s.mmsi)
    edges = [hour_ms, *sorted(stamps), max(hour_ms, min(end, now_ms))]
    gap = max(b - a for a, b in zip(edges, edges[1:]))
    return {"messages": len(stamps), "watched_messages": watched, "vessels": len(vessels), "max_gap_s": gap // 1000}


# ---------------------------------------------------------------- the run

@dataclass
class Context:
    """What a run and its hooks share."""
    region: Any                     # config.FleetRegion
    worker: Worker
    store: AisStore
    state: State
    root: Path                      # <FLEET_VAR>/<region>/ais
    now_ms: int
    source: str = "aisstream"
    run_id: str = ""

    @property
    def computed_at(self) -> str:
        return iso_utc(self.now_ms)


def hooks() -> dict[str, Callable]:
    """CF-46's ``refresh_watch`` and ``match`` from ``skippercast.fleet.ais.match``, when that module exists."""
    name = f"{__package__}.match"
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        return {}
    return {hook: getattr(module, hook) for hook in HOOKS if callable(getattr(module, hook, None))}


def registry_targets(worker: Worker, region_id: str) -> dict[int, VesselRef]:
    """Registry vessels with an MMSI (snapshot pages from the vessels section); an MMSI on two vessels is left out."""
    found: dict[int, VesselRef | None] = {}
    cursor = "v:"
    while cursor and cursor.startswith("v:"):
        page = worker.get("snapshot", region=region_id, cursor=cursor)
        for vessel in page.get("vessels") or []:
            mmsi = str(vessel.get("mmsi") or "")
            if not mmsi.isdigit() or vessel.get("status") == "excluded":
                continue
            ref = VesselRef(vessel["id"], vessel.get("vessel_class"), vessel.get("port_id"))
            found[int(mmsi)] = None if int(mmsi) in found else ref
        cursor = page.get("next")
    return {m: ref for m, ref in found.items() if ref is not None}


def push_heartbeat(ctx: Context) -> dict:
    now, state = ctx.now_ms, ctx.state
    current = now // HOUR * HOUR
    first = max(state.get("hours_done", 0), current - HOURS_BACK * HOUR)
    for hour in range(first, current + HOUR, HOUR):
        state.set_hour(hour, hour_counts(ctx.store, hour, now))
    beat = None
    try:
        beat = json.loads((ctx.root / "heartbeat.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("no heartbeat.json: the listener is not running or has not written one")
    except ValueError as error:
        log.warning("unreadable heartbeat.json: %s", error)
    sent = None
    if isinstance(beat, dict):
        reconnects = _count(beat.get("reconnects"))
        dropped = sum(_count(v) for v in (beat.get("drops") or {}).values())
        previous = state.get("listener")
        if previous and previous.get("started_at") == beat.get("started_at"):
            delta = (max(0, reconnects - previous["reconnects"]), max(0, dropped - previous["dropped"]))
        else:
            delta = (reconnects, dropped)
        state.add_listener_counts(current, *delta)
        state.put("listener", {"started_at": beat.get("started_at"), "reconnects": reconnects, "dropped": dropped})
        sent = {k: beat[k] for k in HEARTBEAT_FIELDS if beat.get(k) is not None}
        sent["dropped"] = dropped
    ctx.worker.post("heartbeat", {"region": ctx.region.id, "heartbeat": sent, "hours": state.hours(first),
                                  "messages_24h": state.messages_since(now - DAY)})
    state.put("hours_done", current)
    return {"hours": (current - first) // HOUR + 1, "heartbeat": sent is not None}


def _count(value) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else 0


def push_trips(ctx: Context, targets: Mapping[int, VesselRef], window: tuple[int, int] | None) -> tuple[dict, set[str]]:
    """Derive and push every target's window; returns counts and the seasons touched."""
    region, now = ctx.region, ctx.now_ms
    settled = now - SETTLE_MS
    oldest = now - int(region.thresholds["retention"]["raw_days"]) * DAY
    longest = int(max(region.thresholds["activity"]["max_open_trip_hours"].values()) * HOUR)
    derived: list[Derived] = []
    for mmsi in sorted(targets):
        if window is None:
            resume = ctx.state.resume(mmsi, ctx.source)
            start = oldest if resume is None else max(oldest, resume)
            end = read_end = settled
        else:
            (start, end), read_end = window, min(window[1] + longest, settled)
        if end <= start:
            continue
        # Positions from an hour before the window, so a departure at its start is seen leaving port; only
        # departures inside the window are kept and replaced. The lead's own trips (the tail of a trip the last
        # run already closed, which starts at sea here) fall before the window and are dropped.
        positions = ctx.store.read_positions(start - LEAD_MS, read_end, [mmsi])
        derived.append(derive(positions, mmsi, targets[mmsi], region, source=ctx.source, window_from=start,
                              window_to=end, now_ms=now, computed_at=ctx.computed_at))
    units = [u for d in derived for u in _units(d)]
    counts = {"vessels": len(derived), "trips": 0, "segments": 0, "events": 0, "requests": 0}
    batch: list[dict] = []
    for index, unit in enumerate(units):
        batch.append(unit)
        following = units[index + 1] if index + 1 < len(units) else None
        if following is None or len(batch) == POST_WINDOWS \
                or sum(u["bytes"] for u in batch) + following["bytes"] > POST_BYTES \
                or sum(len(u["trips"]) for u in batch) + len(following["trips"]) > POST_TRIPS:
            _post_units(ctx, batch, counts)
            batch = []
    if window is None:
        for d in derived:
            ctx.state.set_resume(d.mmsi, ctx.source, d.resume_ms)
    zone = ZoneInfo(region.timezone)
    seasons = set()
    for d in derived:
        first, last = (datetime.fromtimestamp(t / 1000, zone).year for t in (d.window_from, d.window_to - 1))
        seasons.update(str(y) for y in range(first, last + 1))
    return counts, seasons


def _post_units(ctx: Context, units: list[dict], counts: dict) -> None:
    trips = [t for u in units for t in u["trips"]]
    body = {"region": ctx.region.id, "source": ctx.source,
            "replace": [{"mmsi": str(m), "from": iso_utc(a), "to": iso_utc(b)} for m, a, b in (u["window"] for u in units)],
            "trips": trips, "segments": [s for u in units for s in u["segments"]],
            "events": [e.as_row() for u in units for e in u["events"]]}
    ctx.worker.post("activity", body)
    departures = {t["id"]: (int(t["mmsi"]), _ms(t["departed_at"])) for t in trips}
    ctx.state.replace_events(ctx.source, [u["window"] for u in units], [e for u in units for e in u["events"]],
                             departures)
    counts["requests"] += 1
    for key in ("trips", "segments", "events"):
        counts[key] += len(body[key])


def _digest(cell: aggregate.Cell) -> str:
    row = cell.as_row()
    row.pop("computed_at")
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]


def _may_prune(ctx: Context, season: str, allow_prune: bool) -> bool:
    """Prune only when told to, or when the state mirrors the whole season (it existed before the season began)."""
    if allow_prune:
        return True
    begins = datetime(int(season), 1, 1, tzinfo=ZoneInfo(ctx.region.timezone)).timestamp() * 1000
    return ctx.state.get("created_ms", ctx.now_ms) <= begins


def push_aggregates(ctx: Context, seasons: Iterable[str], allow_prune: bool = False) -> dict:
    """Changed cells of each touched season. A season new to the state sends all its cells; the Worker prunes that
    module's other cells of the season only when ``_may_prune`` holds, since aggregates are permanent (design § 5)
    and a fresh or lost state mirrors only the raw store's window."""
    params = aggregate.AggregateParams.from_region(ctx.region)
    counts = {"cells": 0, "deleted": 0, "requests": 0}
    for season in sorted(seasons):
        events = aggregate.prefer_sources(ctx.state.season_events(season), SOURCE_PRECEDENCE)
        cells = aggregate.compute(events, params, now_ms=ctx.now_ms, tz=ctx.region.timezone, computed_at=ctx.computed_at)
        known = ctx.state.cells(season)
        full = not known
        digests = {c.id: _digest(c) for c in cells}
        changed = [c for c in cells if full or known.get(c.id) != digests[c.id]]
        deleted = [] if full else sorted(set(known) - set(digests))
        chunks = max(1, -(-len(changed) // CELLS_PER_POST), -(-len(deleted) // CELLS_PER_POST))
        if not full and not changed and not deleted:
            continue
        prune = full and _may_prune(ctx, season, allow_prune)
        if full and not prune:
            log.warning("season %s is new to the processor state: sending its cells without pruning older ones "
                        "(run with --allow-prune once the state holds the whole season)", season)
        for k in range(chunks):
            part = changed[k * CELLS_PER_POST:(k + 1) * CELLS_PER_POST]
            gone = deleted[k * CELLS_PER_POST:(k + 1) * CELLS_PER_POST]
            body = {"module": params.module, "season": season, "cells": [c.as_row() for c in part], "delete": gone}
            if prune and k == chunks - 1:
                body["prune"] = ctx.computed_at
            ctx.worker.post("activity", {"region": ctx.region.id, "aggregates": body})
            ctx.state.update_cells(season, {c.id: digests[c.id] for c in part}, gone, full and k == 0)
            counts["requests"] += 1
        counts["cells"] += len(changed)
        counts["deleted"] += len(deleted)
    return counts


def run(region, worker: Worker, *, root: Path | None = None, now_ms: int | None = None, source: str = "aisstream",
        window: tuple[int, int] | None = None, mmsis: Iterable[int] | None = None,
        hook_table: Mapping[str, Callable] | None = None, allow_prune: bool = False) -> dict:
    """One processor run (module docstring); ``window`` re-runs only that departure window."""
    if source not in STORES:
        raise ValueError(f"no raw store for source {source!r} yet")
    root = Path(root) if root is not None else ais_root(region.id)
    now = round(time.time() * 1000) if now_ms is None else now_ms
    state = State(root / "state.sqlite")
    ctx = Context(region, worker, STORES[source](root), state, root, now, source,
                  datetime.fromtimestamp(now / 1000, timezone.utc).strftime("ais-%Y%m%dT%H%M%SZ"))
    if state.get("created_ms") is None:
        state.put("created_ms", now)
    state.log_run(ctx.run_id, ctx.computed_at, None, None)
    counts: dict[str, Any] = {}
    try:
        table = hooks() if hook_table is None else dict(hook_table)
        if window is None:
            counts["heartbeat"] = push_heartbeat(ctx)
            if "refresh_watch" in table:
                table["refresh_watch"](ctx)
        targets = registry_targets(worker, region.id)
        if window is None and "match" in table:
            for mmsi, ref in (table["match"](ctx) or {}).items():
                targets.setdefault(mmsi, ref)   # AIS never overrides the registry's MMSI (CF-46 acceptance 3)
        if mmsis is not None:
            wanted = set(mmsis)
            targets = {m: ref for m, ref in targets.items() if m in wanted}
        counts["trips"], seasons = push_trips(ctx, targets, window)
        counts["aggregates"] = push_aggregates(ctx, seasons, allow_prune)
        if window is None:
            try:
                result = ctx.store.apply_retention(retention_limits(region), today=datetime.fromtimestamp(
                    now / 1000, timezone.utc).date())
                counts["retention"] = {"deleted": len(result.deleted_files), "emptied": len(result.emptied)}
            except FileNotFoundError:   # the listener's own retention removed a file first; the next run finishes
                counts["retention"] = {"raced": True}
            from .backfill import retention as backfill_retention   # lazy: backfill imports this module
            counts["backfill_retention"] = backfill_retention(root, region, now)
            worker.post("activity", {"region": region.id, "processed": {"run_id": ctx.run_id, "counts": counts}})
        state.log_run(ctx.run_id, ctx.computed_at, iso_utc(round(time.time() * 1000)), counts)
        return counts
    finally:
        state.close()


# ---------------------------------------------------------------- command line

def _day(text: str) -> date:
    return date.fromisoformat(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais process", description=__doc__.splitlines()[0])
    parser.add_argument("--region", required=True)
    parser.add_argument("--from", dest="start", type=_day, help="first region-local day of a re-run window")
    parser.add_argument("--to", dest="end", type=_day, help="last region-local day of a re-run window (inclusive)")
    parser.add_argument("--source", choices=sorted(STORES), default="aisstream")
    parser.add_argument("--mmsi", type=int, action="append", help="only this MMSI (repeatable)")
    parser.add_argument("--allow-prune", action="store_true",
                        help="let a season new to the state replace the Worker's cells for it (a full rebuild)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if (args.start is None) != (args.end is None) or (args.start and args.end < args.start):
        parser.error("--from and --to go together, --to on or after --from")
    try:
        region = load_region(args.region)
        window = None
        if args.start:
            zone = ZoneInfo(region.timezone)
            window = tuple(round(datetime.combine(d, dtime(0), zone).timestamp() * 1000)
                           for d in (args.start, args.end + timedelta(days=1)))
        counts = run(region, Worker(worker_base()), source=args.source, window=window, mmsis=args.mmsi,
                     allow_prune=args.allow_prune)
    except (FleetConfigError, WorkerError, ValueError) as error:
        print(f"fleet ais process: {error}", file=sys.stderr)
        return 2
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""MMSI matching and the AIS watch list (design.md section 11, CF-46).

The processor (``process.py``) calls two hooks each scheduled run:

``refresh_watch(ctx)``
    reads the watched MMSIs from ``GET /api/fleet/jobs/watch`` and writes the
    listener's ``watch.json`` (``watch.write_watch``, atomic). ``match`` calls it
    again after pushing its updates, so one run leaves the file current.

``match(ctx)``
    scans what the raw store gained since the last run into the processor state,
    matches MMSIs to registry vessels in three stages, pushes the result with
    ``POST /api/fleet/jobs/watch`` and returns the watched MMSIs as targets.

**Stages** (``decide``, pure):

1. *Registry.* A vessel's own ``mmsi`` (FCC ULS, PSIX, an admin decision) with an
   AIS name (the vessel's name or an alias) or call sign that agrees -> ``watched``
   at 0.9 (``fcc-uls``); an admin-set MMSI (``mmsi`` pinned, as a ``set-mmsi``
   decision or an admin edit leaves it) -> ``watched`` at 1.0 (``admin``) whatever AIS says. Statics that
   agree on neither -> ``candidate`` at 0.5 and an ``mmsi`` review. An MMSI never
   heard on AIS gets no row, and one with no statics left keeps its stored row; one held by two vessels is left to the resolver.
2. *Broadcast name.* An MMSI that is no vessel's registry MMSI, broadcasting a
   vessel's name or alias (``ais-static-name``, 0.7) or its call sign (``call-sign``,
   0.8), with a ship type of 30, 37, 60 or 69 (another known type is no match) ->
   ``candidate``. An unknown type or length costs 0.1 and blocks promotion; a
   length more than 20% off the registry's is a contradiction (0.4).
3. *Home port.* A stage-2 candidate seen inside its vessel's own port geofence on
   at least 3 distinct region-local days of the last 30 -> ``watched`` at
   ``thresholds.match.mmsi_auto`` or more (``geofence-presence``); once watched it
   stays watched while the name still matches. Only with a known ship type of
   30/37/60/69 *and* a known length within 20% (design § 11): never when either is
   unknown or the length contradicts, when the vessel already has a registry MMSI
   (the registry is never overridden), when two vessels match, or when the
   vessel has no home port.

A candidate that cannot promote (any blocker above) once it has been seen in the
vessel's home port, one seen there that has not promoted after 7 days, one of a
vessel without a home port after 7 days, and every stage-1 disagreement become
an ``mmsi`` review: ``fingerprint`` ``<vessel_id>|<mmsi>``,
subject the vessel, ``candidate_json`` the AIS evidence, ``proposal_json``
``{vessel_id, mmsi}``. A decided ``reject-mmsi`` marks that pair ``rejected`` for
good; ``set-mmsi`` makes it the vessel's admin MMSI (stage 1).

**Never overriding the registry.** Matching writes watch rows, ``ais.*`` facts and
``mmsi`` reviews only: never a vessel column, never a ``mmsi`` or ``call_sign``
fact. Statics that disagree with a matched vessel (a stale call sign, another
name, an odd length) are recorded as ``method=ais`` facts in their own fields
(``ais.call_sign``, ``ais.name``, ``ais.length_ft``; value ``{mmsi, value}``,
source ``ais-static``), which no resolver rule reads and the public profile never
shows. The processor keeps a registry vessel's attribution of its MMSI over
anything ``match`` returns, and the Worker refuses a watched row that would tie
an MMSI to any vessel but the one holding it in the registry.

**State** (in the processor's ``state.sqlite``): the latest non-empty value of
each static field per MMSI, first and last seen times, position counts per MMSI
and day, and the days each MMSI was inside each port geofence. Each run scans
the store from the last scan to ``now - 10 min``; the first run looks back over
the discovery retention. Statics the state lacks for an MMSI the Worker has a
row for are re-read from the store's whole static retention (never rebuilt from
the row, which has no type or length); with none left, the stored row stands.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from ..normalize import name_norm
from ..ops import validate_ops
from .events import iso_utc
from .process import DAY, HOUR, SETTLE_MS, SOURCE_RIGHTS, VesselRef, WorkerError
from .watch import write_watch

__all__ = ["SHIP_TYPES", "PRESENCE_DAYS", "Static", "Seen", "Decision", "decide", "match", "refresh_watch",
           "read_snapshot", "read_watch_rows", "scan", "MatchState"]

SHIP_TYPES = frozenset({30, 37, 60, 69})   # fishing, pleasure craft, passenger, passenger (no additional information)
LENGTH_TOLERANCE = 0.2
PRESENCE_DAYS = 3
WINDOW_DAYS = 30
REVIEW_AFTER_DAYS = 7
SCAN_SLICE_MS = 6 * HOUR
MAX_REVIEWS_PER_MMSI = 5
ROWS_PER_POST = 500
OPS_PER_POST = 400
FT_PER_M = 3.28084
FACT_SOURCE = "ais-static"
SOURCE_URLS = {"aisstream": "https://aisstream.io/", "marinecadastre": "https://hub.marinecadastre.gov/",
               "datalastic": "https://datalastic.com/"}
CONFIDENCE = {"admin": 1.0, "registry": 0.9, "registry-disagrees": 0.5, "call-sign": 0.8, "ais-static-name": 0.7,
              "unknown": 0.1, "contradicted": 0.4}

log = logging.getLogger("skippercast.fleet.ais.match")


# ---------------------------------------------------------------- records

@dataclass(frozen=True)
class Static:
    """The latest non-empty value of each static field heard from one MMSI."""
    mmsi: int
    ts: int
    source: str
    name: str | None = None
    call_sign: str | None = None
    ship_type: int | None = None
    length_m: float | None = None
    ais_class: str | None = None


@dataclass(frozen=True)
class Seen:
    first_ms: int
    last_ms: int
    last_source: str | None
    positions_30d: int = 0


@dataclass
class Decision:
    rows: list[dict]        # fleet_ais_watch rows (POST /api/fleet/jobs/watch ``rows``)
    facts: list[dict]       # fact.upsert operations (method ais, fields ais.*)
    reviews: list[dict]     # review.open operations (kind mmsi)
    targets: dict[int, VesselRef]


def _call(value) -> str | None:
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    return text or None


def _clean_name(value) -> str | None:
    text = " ".join(str(value or "").replace("@", " ").split())
    return text or None


def _iso(ms: int) -> str:
    return iso_utc(int(ms))


# ---------------------------------------------------------------- the decision (pure)

class _Vessel:
    def __init__(self, row: Mapping[str, Any]):
        self.id = row["id"]
        self.row = row
        self.port_id = row.get("port_id")
        self.vessel_class = row.get("vessel_class")
        self.mmsi = int(row["mmsi"]) if str(row.get("mmsi") or "").isdigit() and int(row["mmsi"]) > 0 else None
        self.call_sign = _call(row.get("call_sign"))
        length = row.get("length_ft")
        self.length_ft = float(length) if isinstance(length, (int, float)) and length > 0 else None
        self.names = {n for n in [row.get("name_norm") or name_norm(row.get("name") or "")] +
                      [a.get("alias_norm") for a in row.get("aliases") or ()] if n}
        # An admin decision (set-mmsi, or an edit) pins the column; the Worker checks the same before it lets an
        # admin row replace a rejected one.
        self.admin_mmsi = self.mmsi is not None and "mmsi" in (row.get("pinned") or ())

    def names_agree(self, static: Static | None) -> bool:
        return bool(static and static.name and name_norm(static.name) in self.names)

    def call_agrees(self, static: Static | None) -> bool:
        return bool(static and static.call_sign and self.call_sign and _call(static.call_sign) == self.call_sign)

    @property
    def ref(self) -> VesselRef:
        return VesselRef(self.id, self.vessel_class, self.port_id)

    def length_check(self, static: Static) -> str:
        """``agrees``, ``unknown`` or ``contradicts`` (AIS length more than 20% off the registry's)."""
        if self.length_ft is None or static.length_m is None:
            return "unknown"
        ais_ft = static.length_m * FT_PER_M
        return "agrees" if abs(ais_ft - self.length_ft) <= LENGTH_TOLERANCE * self.length_ft else "contradicts"


def decide(region, vessels: Iterable[Mapping], reviews: Iterable[Mapping], statics: Mapping[int, Static],
           seen: Mapping[int, Seen], presence: Mapping[int, Mapping[str, int]], prior: Mapping[int, Mapping],
           now_ms: int) -> Decision:
    """Watch rows, ``ais`` facts, ``mmsi`` reviews and targets for one run (module docstring).

    ``presence[mmsi][port_id]`` is the number of distinct region-local days in the
    last 30 the MMSI was inside that port's geofence; ``prior`` the Worker's rows by
    MMSI. Rows go out only for MMSIs heard on AIS.
    """
    auto = float(region.thresholds["match"]["mmsi_auto"])
    now = _iso(now_ms)
    fleet = [_Vessel(v) for v in vessels if v.get("status") != "excluded"]
    by_id = {v.id: v for v in fleet}
    owners: dict[int, list[_Vessel]] = {}
    by_name: dict[str, set[str]] = {}
    by_call: dict[str, set[str]] = {}
    for v in fleet:
        if v.mmsi is not None:
            owners.setdefault(v.mmsi, []).append(v)
        for n in v.names:
            by_name.setdefault(n, set()).add(v.id)
        if v.call_sign and v.mmsi is None:
            by_call.setdefault(v.call_sign, set()).add(v.id)
    rejected = set()
    for r in reviews:
        decision = r.get("decision") or {}
        if r.get("kind") == "mmsi" and r.get("status") == "decided" and decision.get("action") == "reject-mmsi":
            vessel = decision.get("vessel_id") or r.get("subject_id")
            if vessel and str(decision.get("mmsi") or "").isdigit():
                rejected.add((vessel, int(decision["mmsi"])))

    out = Decision([], [], [], {})

    def heard(mmsi: int) -> tuple[Static | None, Seen | None]:
        return statics.get(mmsi), seen.get(mmsi)

    def row(mmsi, vessel_id, method, confidence, status, static: Static | None, sight: Seen | None) -> dict:
        first = sight.first_ms if sight else static.ts
        last = sight.last_ms if sight else static.ts
        source = sight.last_source if sight and sight.last_source else (static.source if static else None)
        item = {"mmsi": str(mmsi), "vessel_id": vessel_id, "match_method": method, "confidence": round(confidence, 3),
                "status": status, "ais_name": static.name if static else None,
                "ais_call_sign": static.call_sign if static else None,
                "ais_class": static.ais_class if static else None, "first_seen_at": _iso(first),
                "last_seen_at": _iso(last), "last_seen_source": source,
                "positions_30d": sight.positions_30d if sight else 0}
        out.rows.append(item)
        return item

    def facts(v: _Vessel, mmsi: int, static: Static, confidence: float, *, name_ok: bool, call_ok: bool) -> None:
        """Disagreeing statics as ais.* facts on the vessel (never its columns)."""
        observed = []
        if static.call_sign and v.call_sign and not call_ok:
            observed.append(("ais.call_sign", static.call_sign))
        if static.name and not name_ok:
            observed.append(("ais.name", static.name))
        if v.length_check(static) == "contradicts":
            observed.append(("ais.length_ft", round(static.length_m * FT_PER_M, 1)))
        for field_, value in observed:
            out.facts.append({"op": "fact.upsert", "vessel_id": v.id, "field": field_,
                              "value_json": {"mmsi": str(mmsi), "value": value}, "source_id": FACT_SOURCE,
                              "source_url": SOURCE_URLS.get(static.source, SOURCE_URLS["aisstream"]), "method": "ais",
                              "confidence": round(confidence, 3), "rights": SOURCE_RIGHTS.get(static.source, "internal-only"),
                              "retrieved_at": _iso(static.ts)})

    def review(v: _Vessel, mmsi: int, static: Static | None, method: str, confidence: float, reason: str,
               days: int) -> None:
        out.reviews.append({
            "op": "review.open", "kind": "mmsi", "fingerprint": f"{v.id}|{mmsi}", "subject_id": v.id,
            "candidate_json": {"mmsi": str(mmsi), "ais_name": static.name if static else None,
                               "ais_call_sign": static.call_sign if static else None,
                               "ship_type": static.ship_type if static else None,
                               "length_ft": round(static.length_m * FT_PER_M, 1) if static and static.length_m else None,
                               "home_port": v.port_id, "home_port_days": days},
            "proposal_json": {"vessel_id": v.id, "mmsi": str(mmsi), "match_method": method, "reason": reason},
            "score": round(confidence, 3), "opened_at": now})

    # ---- stage 1: the registry's own MMSIs
    for mmsi, held in sorted(owners.items()):
        static, sight = heard(mmsi)
        if len(held) > 1 or (static is None and sight is None):
            continue
        v = held[0]
        if (v.id, mmsi) in rejected and not v.admin_mmsi:
            row(mmsi, v.id, "fcc-uls", 0.0, "rejected", static, sight)
            continue
        name_ok, call_ok = v.names_agree(static), v.call_agrees(static)
        if v.admin_mmsi:
            method, confidence, status = "admin", CONFIDENCE["admin"], "watched"
        elif static is None and mmsi in prior:
            continue   # nothing to judge by (statics expired, or a lost state): the stored row stands
        elif static is None:
            method, confidence, status = "fcc-uls", CONFIDENCE["registry-disagrees"], "candidate"   # positions, no static yet
        elif name_ok or call_ok:
            method, confidence, status = "fcc-uls", CONFIDENCE["registry"], "watched"
        else:
            method, confidence, status = "fcc-uls", CONFIDENCE["registry-disagrees"], "candidate"
            review(v, mmsi, static, method, confidence, "registry-statics-disagree", presence.get(mmsi, {}).get(v.port_id, 0))
        row(mmsi, v.id, method, confidence, status, static, sight)
        if static is not None:
            facts(v, mmsi, static, confidence, name_ok=name_ok, call_ok=call_ok)
        if status == "watched":
            out.targets[mmsi] = v.ref

    # ---- stages 2 and 3: broadcast names and calls of MMSIs the registry does not hold
    for mmsi in sorted(statics):
        if mmsi in owners:
            continue
        static, sight = heard(mmsi)
        if static.ship_type is not None and static.ship_type not in SHIP_TYPES:
            continue
        hits: dict[str, str] = {}
        if static.name and (norm := name_norm(static.name)):
            hits.update({vid: "ais-static-name" for vid in by_name.get(norm, ())})
        if static.call_sign:
            hits.update({vid: "call-sign" for vid in by_call.get(_call(static.call_sign), ())})
        if not hits:
            continue
        open_hits = {vid: m for vid, m in hits.items() if (vid, mmsi) not in rejected}
        if not open_hits:
            row(mmsi, sorted(hits)[0], hits[sorted(hits)[0]], 0.0, "rejected", static, sight)
            continue
        days = {vid: presence.get(mmsi, {}).get(by_id[vid].port_id, 0) if by_id[vid].port_id else 0 for vid in open_hits}
        if len(open_hits) == 1:
            chosen = next(iter(open_hits))
        else:
            present = [vid for vid in sorted(open_hits) if days[vid] > 0]
            chosen = present[0] if len(present) == 1 else None
        if chosen is None:   # two or more vessels: no promotion; review those seen at home
            row(mmsi, None, open_hits[sorted(open_hits)[0]], CONFIDENCE["contradicted"], "candidate", static, sight)
            for vid in [v for v in sorted(open_hits) if days[v] > 0][:MAX_REVIEWS_PER_MMSI]:
                review(by_id[vid], mmsi, static, open_hits[vid], CONFIDENCE["contradicted"], "several-vessels", days[vid])
            continue
        v, method, home_days = by_id[chosen], open_hits[chosen], days[chosen]
        length = v.length_check(static)
        confidence = CONFIDENCE[method]
        if static.ship_type is None or length == "unknown":
            confidence -= CONFIDENCE["unknown"]
        blockers = []   # design § 11: promotion needs a type of 30/37/60/69 and a length within 20%, both known
        if length == "contradicts":
            confidence = CONFIDENCE["contradicted"]
            blockers.append("length-contradicts")
        elif length == "unknown":
            blockers.append("length-unknown")
        if static.ship_type is None:
            blockers.append("type-unknown")
        if v.mmsi is not None:
            blockers.append("vessel-has-registry-mmsi")
        if not v.port_id:
            blockers.append("no-home-port")
        before = prior.get(mmsi) or {}
        sticky = before.get("status") == "watched" and before.get("vessel_id") == v.id
        if not blockers and (home_days >= PRESENCE_DAYS or sticky):
            confidence = max(auto, confidence)
            row(mmsi, v.id, "geofence-presence", confidence, "watched", static, sight)
            facts(v, mmsi, static, confidence, name_ok=v.names_agree(static), call_ok=v.call_agrees(static))
            out.targets[mmsi] = v.ref
            continue
        row(mmsi, v.id, method, confidence, "candidate", static, sight)
        first = sight.first_ms if sight else static.ts
        waited = now_ms - min(first, _ms(before.get("first_seen_at")) or first) >= REVIEW_AFTER_DAYS * DAY
        if (blockers and home_days > 0) or (not v.port_id and waited) or (home_days > 0 and waited):
            review(v, mmsi, static, method, confidence, blockers[0] if blockers else "few-home-port-days", home_days)

    # ---- watched rows: demoted when their statics no longer match; left as they are when there are no statics
    derived = {int(r["mmsi"]) for r in out.rows}
    for mmsi, before in sorted(prior.items()):
        if mmsi in derived or before.get("status") != "watched":
            continue
        if mmsi in statics or mmsi in owners:
            out.rows.append({**{k: before.get(k) for k in WATCH_COLUMNS}, "mmsi": str(mmsi), "status": "candidate"})
        elif before.get("vessel_id") in by_id:
            out.targets[mmsi] = by_id[before["vessel_id"]].ref
    return out


WATCH_COLUMNS = ("mmsi", "vessel_id", "match_method", "confidence", "status", "ais_name", "ais_call_sign", "ais_class",
                 "first_seen_at", "last_seen_at", "last_seen_source", "positions_30d")


def _ms(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return round(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


# ---------------------------------------------------------------- state

_DDL = """
CREATE TABLE IF NOT EXISTS match_statics (mmsi INTEGER PRIMARY KEY, ts INTEGER NOT NULL, source TEXT NOT NULL,
  name TEXT, call_sign TEXT, ship_type INTEGER, length_m REAL, ais_class TEXT);
CREATE TABLE IF NOT EXISTS match_seen (mmsi INTEGER PRIMARY KEY, first_ms INTEGER NOT NULL, last_ms INTEGER NOT NULL,
  last_source TEXT);
CREATE TABLE IF NOT EXISTS match_days (mmsi INTEGER NOT NULL, day TEXT NOT NULL, positions INTEGER NOT NULL,
  PRIMARY KEY (mmsi, day));
CREATE TABLE IF NOT EXISTS match_presence (mmsi INTEGER NOT NULL, port_id TEXT NOT NULL, day TEXT NOT NULL,
  PRIMARY KEY (mmsi, port_id, day));
"""


class MatchState:
    """The matcher's tables in the processor's ``state.sqlite`` (``process.State``)."""

    def __init__(self, state):
        self.state = state
        self.db = state.db
        self.db.executescript(_DDL)

    def statics(self) -> dict[int, Static]:
        return {r[0]: Static(*r) for r in self.db.execute(
            "SELECT mmsi,ts,source,name,call_sign,ship_type,length_m,ais_class FROM match_statics")}

    def seen(self, since_day: str) -> dict[int, Seen]:
        counts = dict(self.db.execute("SELECT mmsi, SUM(positions) FROM match_days WHERE day>=? GROUP BY mmsi",
                                      (since_day,)).fetchall())
        return {m: Seen(a, b, s, int(counts.get(m, 0))) for m, a, b, s in
                self.db.execute("SELECT mmsi,first_ms,last_ms,last_source FROM match_seen")}

    def presence(self, since_day: str) -> dict[int, dict[str, int]]:
        out: dict[int, dict[str, int]] = {}
        for mmsi, port, n in self.db.execute("SELECT mmsi, port_id, COUNT(*) FROM match_presence WHERE day>=? "
                                             "GROUP BY mmsi, port_id", (since_day,)):
            out.setdefault(mmsi, {})[port] = n
        return out

    def prune(self, before_day: str) -> None:
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute("DELETE FROM match_days WHERE day<?", (before_day,))
            self.db.execute("DELETE FROM match_presence WHERE day<?", (before_day,))

    def add(self, statics: Iterable, positions: Iterable, ports, zone: ZoneInfo) -> None:
        """Fold one slice of the store into the tables."""
        known = self.statics()
        changed: dict[int, Static] = {}
        sightings: dict[int, list] = {}
        for s in statics:
            base = changed.get(s.mmsi) or known.get(s.mmsi) or Static(s.mmsi, s.ts, s.source)
            fresh = s.ts >= base.ts
            length = (s.dim_bow + s.dim_stern) if s.dim_bow and s.dim_stern else None
            values = {"name": _clean_name(s.name), "call_sign": _call(s.call_sign), "ship_type": s.ship_type or None,
                      "length_m": float(length) if length else None, "ais_class": s.ais_class or None}
            updates = {k: v for k, v in values.items() if v is not None and (fresh or getattr(base, k) is None)}
            if fresh:
                updates.update(ts=s.ts, source=s.source)
            changed[s.mmsi] = replace(base, **updates)
            _sight(sightings, s.mmsi, s.ts, s.source)
        days: Counter = Counter()
        inside: set[tuple[int, str, str]] = set()
        checked: set[tuple] = set()
        boxes = [(p, min(x for x, _ in p.geofence), max(x for x, _ in p.geofence), min(y for _, y in p.geofence),
                  max(y for _, y in p.geofence)) for p in ports]
        for p in positions:
            day = datetime.fromtimestamp(p.ts / 1000, zone).date().isoformat()
            days[(p.mmsi, day)] += 1
            _sight(sightings, p.mmsi, p.ts, p.source)
            key = (p.mmsi, day, round(p.lat, 4), round(p.lon, 4))
            if key in checked:
                continue
            checked.add(key)
            for port, w, e, s, n in boxes:
                if w <= p.lon <= e and s <= p.lat <= n and port.contains(p.lat, p.lon):
                    inside.add((p.mmsi, port.id, day))
        with self.db:
            self.db.execute("BEGIN")
            self.db.executemany("INSERT OR REPLACE INTO match_statics VALUES(?,?,?,?,?,?,?,?)",
                                [(s.mmsi, s.ts, s.source, s.name, s.call_sign, s.ship_type, s.length_m, s.ais_class)
                                 for s in changed.values()])
            self.db.executemany("""INSERT INTO match_seen VALUES(?,?,?,?) ON CONFLICT(mmsi) DO UPDATE SET
              first_ms=MIN(first_ms, excluded.first_ms),
              last_source=CASE WHEN excluded.last_ms>=last_ms THEN excluded.last_source ELSE last_source END,
              last_ms=MAX(last_ms, excluded.last_ms)""", [(m, a, b, src) for m, (a, b, src) in sightings.items()])
            self.db.executemany("""INSERT INTO match_days VALUES(?,?,?) ON CONFLICT(mmsi, day)
              DO UPDATE SET positions=positions+excluded.positions""", [(m, d, n) for (m, d), n in days.items()])
            self.db.executemany("INSERT OR IGNORE INTO match_presence VALUES(?,?,?)", sorted(inside))


def _sight(sightings: dict, mmsi: int, ts: int, source: str) -> None:
    first, last, src = sightings.get(mmsi, (ts, ts, source))
    sightings[mmsi] = (min(first, ts), max(last, ts), source if ts >= last else src)


def scan(ctx, mstate: MatchState) -> dict:
    """Fold the store's rows from the last scan to ``now - 10 min`` into the state, a slice at a time."""
    end = ctx.now_ms - SETTLE_MS
    lookback = int(ctx.region.thresholds["retention"]["discovery_days"]) * DAY
    start = ctx.state.get("match_scanned_ms") or end - lookback
    start = max(start, end - int(ctx.region.thresholds["retention"]["raw_days"]) * DAY)
    zone = ZoneInfo(ctx.region.timezone)
    slices = 0
    for a in range(start, end, SCAN_SLICE_MS):
        b = min(end, a + SCAN_SLICE_MS)
        positions = [p for table in ("positions", "discovery") for p in ctx.store.read_positions(a, b, table=table)]
        mstate.add(ctx.store.read_statics(a, b), positions, ctx.region.ports, zone)
        slices += 1
    if end > start:
        ctx.state.put("match_scanned_ms", end)
    mstate.prune(_day(ctx.now_ms - WINDOW_DAYS * DAY, zone))
    return {"from": _iso(start), "to": _iso(end), "slices": slices}


def _day(ms: int, zone: ZoneInfo) -> str:
    return datetime.fromtimestamp(ms / 1000, zone).date().isoformat()


# ---------------------------------------------------------------- the Worker

def read_snapshot(worker, region_id: str) -> tuple[list[dict], list[dict]]:
    """Every registry vessel and decided review of the region (snapshot pages from the vessels section on)."""
    vessels, reviews, cursor = [], [], "v:"
    while cursor:
        page = worker.get("snapshot", region=region_id, cursor=cursor)
        vessels.extend(page.get("vessels") or [])
        reviews.extend(page.get("reviews") or [])
        cursor = page.get("next")
    return vessels, reviews


def read_watch_rows(worker, region_id: str, status: str | None = None) -> list[dict]:
    """``GET /api/fleet/jobs/watch`` pages: the region's watch rows by MMSI."""
    rows, cursor = [], ""
    while True:
        params = {"region": region_id, "cursor": cursor}
        if status:
            params["status"] = status
        page = worker.get("watch", **params)
        rows.extend(page.get("rows") or [])
        cursor = page.get("next")
        if not cursor:
            return rows


def refresh_watch(ctx) -> dict:
    """Write ``watch.json`` from the Worker's watched rows (hook 1)."""
    watched = sorted({int(r["mmsi"]) for r in read_watch_rows(ctx.worker, ctx.region.id, "watched")
                      if str(r.get("mmsi") or "").isdigit()})
    write_watch(ctx.root / "watch.json", ctx.region.id, watched,
                generated_at=datetime.fromtimestamp(ctx.now_ms / 1000, timezone.utc))
    return {"watched": len(watched)}


def push(ctx, decision: Decision) -> dict:
    """POST the rows, then the facts and reviews, in chunks under the Worker's limits."""
    ops = decision.facts + decision.reviews
    _rows, errors = validate_ops(ops, ctx.region.id)
    if errors:
        raise WorkerError(f"match produced invalid operations: {errors[:3]}")
    counts = {"rows": len(decision.rows), "facts": len(decision.facts), "reviews": len(decision.reviews), "requests": 0}
    base = {"region": ctx.region.id, "run_id": ctx.run_id}
    for k in range(0, len(decision.rows), ROWS_PER_POST):
        ctx.worker.post("watch", {**base, "rows": decision.rows[k:k + ROWS_PER_POST]})
        counts["requests"] += 1
    for k in range(0, len(ops), OPS_PER_POST):
        ctx.worker.post("watch", {**base, "ops": ops[k:k + OPS_PER_POST]})
        counts["requests"] += 1
    return counts


def match(ctx) -> dict[int, VesselRef]:
    """Hook 2: scan, decide, push, refresh ``watch.json``; the watched MMSIs and their vessels."""
    mstate = MatchState(ctx.state)
    zone = ZoneInfo(ctx.region.timezone)
    scanned = scan(ctx, mstate)
    vessels, reviews = read_snapshot(ctx.worker, ctx.region.id)
    prior = {int(r["mmsi"]): r for r in read_watch_rows(ctx.worker, ctx.region.id) if str(r.get("mmsi") or "").isdigit()}
    since = _day(ctx.now_ms - WINDOW_DAYS * DAY, zone)
    missing = sorted(set(prior) - set(mstate.statics()))
    if missing:   # a lost or young state: the real statics from the store's whole static retention, never stand-ins
        start = ctx.now_ms - int(ctx.region.thresholds["retention"]["static_days"]) * DAY
        mstate.add(ctx.store.read_statics(start, ctx.now_ms - SETTLE_MS, missing), (), ctx.region.ports, zone)
    statics, seen = mstate.statics(), mstate.seen(since)
    for mmsi, before in prior.items():   # sightings the state lost: the Worker's row stands in
        if mmsi not in seen and before.get("first_seen_at"):
            seen[mmsi] = Seen(_ms(before["first_seen_at"]), _ms(before.get("last_seen_at")) or ctx.now_ms,
                              before.get("last_seen_source"), int(before.get("positions_30d") or 0))
    decision = decide(ctx.region, vessels, reviews, statics, seen, mstate.presence(since), prior, ctx.now_ms)
    pushed = push(ctx, decision)
    refreshed = refresh_watch(ctx)
    log.info("match: scanned %s; %s; watch.json %s", scanned, pushed, refreshed)
    return decision.targets

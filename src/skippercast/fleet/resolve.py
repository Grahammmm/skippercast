"""Entity resolution: adapter candidates against the registry snapshot, as registry operations (design section 7).

``resolve(snapshot, candidates, config, now)`` assigns every candidate to a
vessel, opens a review, or creates a vessel, then computes the resolved columns
of each vessel it touched and returns the operations (``vessel.upsert``,
``fact.upsert``, ``alias.upsert``, ``review.open``, ``change.record``) for a
sink. Steps, in order, per candidate:

1. Normalise (``normalize``): ``name_norm``, stable keys, port and landing hints,
   phones to E.164, URLs without tracking parameters.
2. Prior decisions: a decided ``merge`` review for the candidate's fingerprint
   (source id + record id or URL) is followed: ``same-vessel`` assigns,
   ``new-vessel`` creates, a dismissed review skips the candidate.
3. Stable keys in order ``uscg_doc``, ``state_reg``, ``hull_id``, ``mmsi``,
   ``call_sign``. One vessel matched: assign at 1.0, or 0.9 when only the call
   sign matched (call signs are reissued; a call sign whose vessel holds a
   different value of another key does not match). Different vessels matched:
   a ``merge`` review. A key match whose name wins the resolved name records
   the old name as a ``former-name`` alias and a ``renamed`` change.
4. Fuzzy fallback: 0.55 x name similarity (Jaro-Winkler on ``name_norm``, 1.0
   on an alias, 0 for a ``NEW`` variant) + 0.25 x same port + 0.10 x same
   landing + 0.10 x length within 10% (each unknown part 0.5); a name
   similarity under 0.8 is no match at all, so unrelated boats of one port
   never reach the review queue on port, landing and length alone. At least
   ``thresholds.match.auto_merge``: assign; at least ``review_min``: a ``merge``
   review with the top two; else a new vessel.
5. A vessel holding a different value of a stable key the candidate has is never
   a fuzzy match: same name and port with different keys are two vessels.
6. ``vessel_class`` facts from different sources at confidence >= 0.7 that
   disagree open a ``class`` review (unless the column is pinned).
7. A winning ``scope`` fact ``{"in_scope": false, ...}`` sets ``status`` to
   ``excluded``, so the boat is not rediscovered as new each run.

Candidates are processed in a fixed order (strongest creation key first, then
fingerprint), so the output does not depend on the order adapters listed them,
and running resolve twice on the same input gives the same operations.

Columns are computed from the vessel's non-superseded facts (the snapshot's,
when it carries them, plus this run's; this run's facts replace the stored ones
of the same field and source): the first source in the field's priority
(``catalog/fleet/resolver.json`` merged with the region's
``resolver_overrides``), then the highest confidence, then the latest
``retrieved_at``; facts below the rule's ``min_confidence`` never win. A
winning admin fact whose value is null means "no value": the column is
cleared and no lower source fills it. Pinned columns are never sent (the name
pair, which every upsert needs, is sent as stored). A column no fact wins is
left out of the upsert, so the stored value stays. The Worker snapshot carries
no fact values, but each vessel's ``sources`` (the id, field, source and
confidence of its current scalar facts) is the winning-source record: a stored
fact known only from it ranks like any other, and when it wins, the column is
left as stored. So a lower-priority source reporting a new value never
overwrites what a higher-priority source set.

The ``operator`` field's winning value (an entity name) becomes ``operator_id``:
the snapshot operator of the same normalised name, else a new operator whose id
is ``sha256(region|operator|name_norm)[:32]``, sent as ``operator.upsert``.

``extra_facts`` (vessel id -> facts, the enrich-code step's) join the facts of
a vessel this run's candidates were assigned to.

Only an admin fact may be null; a null from any other source is ignored.

Vessel ids are ``sha256(region:creation_key)[:32]`` with the strongest key at
creation (``uscg:``, ``reg:``, ``hin:``, ``mmsi:``, ``cs:``, else
``name-port:<slug>|<port>``). Slugs are unique against every snapshot vessel
slug, every advisor boat slug and the slugs created in this run.

``fact.upsert`` operations carry no ``supersedes``; superseding is ingest's
(design section 9). Offerings, departures and the change kinds other than
``renamed`` are the ingest and refresh steps'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping

from . import ops
from .adapters.base import Candidate, Fact
from .normalize import clean_url, name_norm, name_similarity, phone_e164, slugify

__all__ = ["COLUMNS", "KEY_ORDER", "STORED", "Resolution", "ResolverConfig", "Snapshot", "fingerprint", "op_sort_key", "resolve",
           "winner"]

KEY_ORDER = ("uscg_doc", "state_reg", "hull_id", "mmsi", "call_sign")
KEY_PREFIX = {"uscg_doc": "uscg", "state_reg": "reg", "hull_id": "hin", "mmsi": "mmsi", "call_sign": "cs"}
# resolver field (fact field) -> fleet_vessels column
COLUMNS = {
    "name": "name", "vessel_class": "vessel_class", "waters": "waters_json", "port": "port_id", "landing": "landing_id",
    "uscg_doc": "uscg_doc", "state_reg": "state_reg", "hull_id": "hull_id", "call_sign": "call_sign", "mmsi": "mmsi",
    "year_built": "year_built", "passengers_max": "passengers_max", "bunks": "bunks", "length_ft": "length_ft",
    "beam_ft": "beam_ft", "cruise_kn": "cruise_kn", "website": "website", "booking_url": "booking_url",
    "booking_platform": "booking_platform", "phone_business": "phone_business", "email_business": "email_business",
}
TARGET = tuple(c for c in COLUMNS.values() if c != "name")  # completeness: the share of these filled
CLASS_REVIEW_MIN = 0.7
SLUG_MAX = 80
NAME_MIN = 0.8  # below this name similarity a vessel is no fuzzy match, whatever the port says
ALIAS_KIND = {"ais-static": "ais-name", "teck-reports": "report-name"}
VESSEL_CHECKS = ops.SPECS["vessel.upsert"][1]
STORED = type("Stored", (), {"__repr__": lambda self: "STORED"})()  # a Worker-stored fact's value: known to exist, not sent


# ---- configuration and snapshot ---------------------------------------------------------

@dataclass(frozen=True)
class ResolverConfig:
    """What resolve needs from a fleet region: rules, match thresholds, port and landing ids."""
    region: str
    rules: Mapping[str, Any]                         # field -> ResolverRule (priority, min_confidence)
    auto_merge: float
    review_min: float
    ports: Mapping[str, str]                         # port id -> name
    landings: Mapping[str, tuple[str, str]]          # landing id -> (name, port id)

    @classmethod
    def from_region(cls, region) -> "ResolverConfig":
        match = region.thresholds["match"]
        return cls(region.id, region.resolver, float(match["auto_merge"]), float(match["review_min"]),
                   {p.id: p.name for p in region.ports}, {x.id: (x.name, x.port) for x in region.landings})

    def port_id(self, hint: Any) -> str | None:
        landing = self.landing_id(hint)
        return _lookup(hint, dict(self.ports)) or (self.landings[landing][1] if landing else None)

    def landing_id(self, hint: Any) -> str | None:
        return _lookup(hint, {k: v[0] for k, v in self.landings.items()})


def _lookup(hint: Any, names: Mapping[str, str]) -> str | None:
    if not isinstance(hint, str) or not hint.strip():
        return None
    if hint in names:
        return hint
    slug, norm = slugify(hint), name_norm(hint)
    if slug in names:
        return slug
    for ident in sorted(names):
        if norm and name_norm(names[ident]) == norm:
            return ident
    return None


def _pinned(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return frozenset({"*"})
        if isinstance(value, dict):
            return frozenset(value)
        return frozenset({"*"})
    return frozenset(value or ())


@dataclass
class Snapshot:
    """The registry as resolve sees it (the Worker's ``GET /api/fleet/jobs/snapshot`` shape).

    ``vessels`` carry their columns, ``waters`` (parsed), ``pinned`` (column
    names, ``*`` for all), ``aliases``, ``offerings`` and, from the Worker,
    ``sources`` (the winning-source record: ``{id, field, source_id, confidence,
    retrieved_at}`` of each current scalar fact, no values); ``reviews`` are the
    decided and dismissed ones with ``decision`` parsed. ``advisor_slugs`` are
    the ``advisor_boats`` slugs a vessel slug must not take. ``facts`` are the
    non-superseded facts of the region's vessels (``value`` parsed), or None
    when the source carries none (the Worker snapshot).
    """
    vessels: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    operators: list = field(default_factory=list)
    advisor_slugs: frozenset = frozenset()
    facts: list | None = None

    @classmethod
    def from_pages(cls, pages: Iterable[Mapping[str, Any]]) -> "Snapshot":
        """Join the Worker snapshot pages (operators, vessels, reviews; ``advisor_slugs`` and ``facts`` if present)."""
        out, slugs, facts = cls(), set(), None
        for page in pages:
            out.operators += list(page.get("operators") or ())
            out.vessels += list(page.get("vessels") or ())
            out.reviews += list(page.get("reviews") or ())
            slugs |= set(page.get("advisor_slugs") or ())
            if page.get("facts") is not None:
                facts = (facts or []) + list(page["facts"])
        out.advisor_slugs, out.facts = frozenset(slugs), facts
        return out

    @classmethod
    def from_sqlite(cls, db, region: str, facts: bool = True) -> "Snapshot":
        """The same shape from a staging database (``SqliteSink.db``), with its facts; ``facts=False`` gives
        the Worker's shape instead (no facts, each vessel's ``sources`` as ``server/fleet/jobs.ts`` selects them)."""
        def rows(sql, *args):
            cursor = db.execute(sql, args)
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

        def parsed(text):
            return None if text is None else json.loads(text)

        aliases: dict[str, list] = {}
        for row in rows("SELECT a.* FROM fleet_aliases a JOIN fleet_vessels v ON v.id=a.vessel_id WHERE v.region=? "
                        "ORDER BY a.vessel_id, a.alias_norm", region):
            aliases.setdefault(row.pop("vessel_id"), []).append(row)
        children: dict[str, dict[str, list]] = {"offerings": {}, "sources": {}}
        for row in rows("SELECT o.* FROM fleet_offerings o JOIN fleet_vessels v ON v.id=o.vessel_id WHERE v.region=? "
                        "ORDER BY o.vessel_id, o.id", region):
            for col in ("days", "target_species", "source_fact_ids"):
                row[col] = parsed(row.pop(f"{col}_json"))
            children["offerings"].setdefault(row.pop("vessel_id"), []).append(row)
        if not facts:
            for row in rows("SELECT f.vessel_id, f.id, f.field, f.source_id, f.confidence, f.retrieved_at "
                            "FROM fleet_vessel_facts f JOIN fleet_vessels v ON v.id=f.vessel_id WHERE v.region=? "
                            "AND f.superseded_at IS NULL AND instr(f.field, '[]')=0 ORDER BY f.vessel_id, f.id", region):
                children["sources"].setdefault(row.pop("vessel_id"), []).append(row)
        vessels = []
        for row in rows("SELECT * FROM fleet_vessels WHERE region=? ORDER BY id", region):
            row["waters"], row["pinned"] = parsed(row.pop("waters_json")), sorted(_pinned(row.pop("pinned_json")))
            row["aliases"] = aliases.get(row["id"], [])
            row["offerings"] = children["offerings"].get(row["id"], [])
            if not facts:
                row["sources"] = children["sources"].get(row["id"], [])
            vessels.append(row)
        reviews = []
        for row in rows("SELECT * FROM fleet_reviews WHERE region=? AND status<>'open' ORDER BY id", region):
            for col in ("candidate", "proposal", "decision"):
                row[col] = parsed(row.pop(f"{col}_json"))
            reviews.append(row)
        stored = []
        for row in rows("SELECT f.* FROM fleet_vessel_facts f JOIN fleet_vessels v ON v.id=f.vessel_id "
                        "WHERE v.region=? AND f.superseded_at IS NULL ORDER BY f.id", region) if facts else ():
            row["value"] = parsed(row.pop("value_json"))
            stored.append(row)
        operators = rows("SELECT id, slug, name FROM fleet_operators WHERE region=? ORDER BY id", region)
        slugs = frozenset(s for (s,) in db.execute("SELECT slug FROM advisor_boats"))
        return cls(vessels, reviews, operators, slugs, stored if facts else None)


@dataclass
class Resolution:
    ops: list                         # registry operations, vessels first
    assignments: dict                 # candidate fingerprint -> vessel id, or None (under review or skipped)
    scores: dict                      # candidate fingerprint -> match score of its assignment (1.0 created or decided)
    created: list                     # ids of the vessels created in this run
    reviews: list                     # ids of the reviews opened (or refreshed)
    skipped: list                     # {"fingerprint", "reason"} for candidates and facts left out


# ---- working records ----------------------------------------------------------------------

@dataclass(frozen=True)
class _Fact:
    id: str
    field: str
    value: Any
    source_id: str
    source_url: str
    method: str
    confidence: float
    rights: str
    retrieved_at: str
    value_key: str


@dataclass
class _Cand:
    raw: Candidate
    fp: str
    name: str
    norm: str
    keys: dict
    port: str | None
    landing: str | None
    length: float | None
    facts: list = field(default_factory=list)   # normalised Fact, not yet bound to a vessel
    url: str | None = None                       # the first https source URL, for aliases


@dataclass
class _Vessel:
    id: str
    slug: str
    name: str
    norm: str
    keys: dict
    port: str | None
    landing: str | None
    length: float | None
    aliases: dict                                 # alias_norm -> stored alias row
    pinned: frozenset
    stored: dict | None                           # the snapshot row; None when created in this run
    creation_key: str | None = None
    cands: list = field(default_factory=list)     # (candidate, score)
    extra: list = field(default_factory=list)     # enrich-code facts (resolve's extra_facts)


def fingerprint(candidate: Candidate) -> str:
    """What a decided review remembers: ``source_id|record_id`` when the adapter set ``record_id``, else
    ``source_id|name_norm|port_hint|first source URL`` (cleaned), so boats listed on one page stay apart."""
    if candidate.record_id:
        text = f"{candidate.source_id}|{candidate.record_id}"
    else:
        urls = sorted(u for f in candidate.facts if (u := clean_url(f.source_url)))
        text = "|".join((candidate.source_id, name_norm(candidate.name), candidate.port_hint or "",
                         urls[0] if urls else ""))
    return text if len(text) <= 400 else f"{candidate.source_id}|sha256:{ops.sha256(text)[:32]}"


def _key(kind: str, value: Any) -> str | None:
    if value is None:
        return None
    text = "".join(str(value).split()).upper()
    if kind == "mmsi":
        text = "".join(c for c in text if c.isdigit())
    return text or None


def _normal_value(field_: str, value: Any, config: ResolverConfig) -> Any:
    if field_ == "phone_business":
        return phone_e164(value) or value
    if field_ in ("website", "booking_url"):
        return clean_url(value) or value
    if field_ in KEY_PREFIX:
        return _key(field_, value) or value
    if field_ == "port":
        return config.port_id(value) or value
    if field_ == "landing":
        return config.landing_id(value) or value
    if field_ == "email_business" and isinstance(value, str):
        return value.strip()
    return value


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def winner(facts: Iterable, rule) -> Any:
    """The winning fact of one field under ``rule`` (priority, then confidence, then latest), or None."""
    eligible = [f for f in facts if f.source_id in rule.priority
                and (f.source_id == "admin" or f.confidence >= rule.min_confidence)]
    eligible.sort(key=lambda f: (f.value_key, f.id))
    eligible.sort(key=lambda f: f.retrieved_at, reverse=True)
    eligible.sort(key=lambda f: (rule.priority.index(f.source_id), -f.confidence))
    return eligible[0] if eligible else None


def _column_value(col: str, value: Any) -> tuple[bool, Any]:
    """(ok, value as the upsert sends it) for a resolved column value."""
    if value is None:
        return True, None
    try:
        VESSEL_CHECKS[col](value, col)
    except ops.OpError:
        return False, None
    return True, ops.plain(value)


# ---- the resolver -------------------------------------------------------------------------

class _Resolver:
    def __init__(self, snapshot: Snapshot, config: ResolverConfig, now: str):
        self.config, self.now = config, ops.iso(now, "now")
        self.vessels: dict[str, _Vessel] = {}
        self.index: dict[tuple[str, str], set] = {}
        self.slugs = set(snapshot.advisor_slugs)
        self.decided = {r["id"]: r for r in snapshot.reviews if r.get("status") in ("decided", "dismissed")}
        self.stored_facts: dict[str, list[_Fact]] = {}
        self.ops: list[dict] = []
        self.assignments: dict[str, str | None] = {}
        self.scores: dict[str, float] = {}
        self.created: list[str] = []
        self.review_ids: list[str] = []
        self.skipped: list[dict] = []
        for row in snapshot.vessels:
            self.slugs.add(row["slug"])
            keys = {k: _key(k, row.get(k)) for k in KEY_ORDER if row.get(k)}
            vessel = _Vessel(row["id"], row["slug"], row["name"], row["name_norm"], keys, row.get("port_id"),
                             row.get("landing_id"), _float(row.get("length_ft")),
                             {a["alias_norm"]: a for a in row.get("aliases") or ()}, _pinned(row.get("pinned")), row)
            self._add(vessel)
        for row in snapshot.facts or ():
            self.stored_facts.setdefault(row["vessel_id"], []).append(_Fact(
                row["id"], row["field"], row.get("value"), row["source_id"], row["source_url"], row.get("method", ""),
                float(row["confidence"]), row.get("rights", ""), row["retrieved_at"],
                row.get("value_key") or ops.value_key(row.get("value"))))
        if snapshot.facts is None:  # the Worker's winning-source record: a stored fact ranks, its value stays stored
            for row in snapshot.vessels:
                self.stored_facts[row["id"]] = [
                    _Fact(s["id"], s["field"], STORED, s["source_id"], "", "", float(s["confidence"]), "",
                          s["retrieved_at"], "") for s in row.get("sources") or ()]
        self.operators = {name_norm(o["name"]): o["id"] for o in sorted(snapshot.operators, key=lambda o: o["id"])}
        self.operator_slugs = {o["slug"] for o in snapshot.operators}

    # -- index

    def _add(self, vessel: _Vessel) -> None:
        self.vessels[vessel.id] = vessel
        for kind, value in vessel.keys.items():
            self.index.setdefault((kind, value), set()).add(vessel.id)

    def _learn(self, vessel: _Vessel, cand: _Cand) -> None:
        """What later candidates in this run match on: keys, port, landing and length the vessel lacked."""
        for kind, value in cand.keys.items():
            if kind not in vessel.keys:
                vessel.keys[kind] = value
                self.index.setdefault((kind, value), set()).add(vessel.id)
        vessel.port = vessel.port or cand.port
        vessel.landing = vessel.landing or cand.landing
        vessel.length = vessel.length or cand.length

    # -- candidates

    def prepare(self, raw: Candidate) -> _Cand | None:
        fp = fingerprint(raw)
        norm = name_norm(raw.name)
        if not norm:
            self.skipped.append({"fingerprint": fp, "reason": "no name"})
            self.assignments[fp] = None
            return None
        keys = {k: v for k in KEY_ORDER if (v := _key(k, raw.keys.get(k)))}
        facts = []
        for fact in raw.facts:
            facts.append(Fact(fact.field, _normal_value(fact.field, fact.value, self.config), fact.source_id,
                              fact.source_url, fact.method, fact.confidence, fact.rights, fact.retrieved_at))
        port = self.config.port_id(raw.port_hint) or self.config.port_id(raw.landing_hint)
        lengths = sorted((-f.confidence, v) for f in facts if f.field == "length_ft" and (v := _float(f.value)))
        urls = sorted(u for f in facts if (u := ops.https_url(f.source_url)))
        return _Cand(raw, fp, raw.name.strip(), norm, keys, port, self.config.landing_id(raw.landing_hint),
                     lengths[0][1] if lengths else None, facts, urls[0] if urls else None)

    @staticmethod
    def order(cand: _Cand) -> tuple:
        strength = next((i for i, k in enumerate(KEY_ORDER) if k in cand.keys), len(KEY_ORDER))
        return strength, cand.fp

    def run(self, cand: _Cand) -> None:
        decided = self.decided.get(ops.review_id("merge", cand.fp))
        if decided is not None:
            return self.follow(cand, decided)
        hits = self.key_hits(cand)
        if len(hits) > 1:
            ranked = sorted(hits, key=lambda v: (min(KEY_ORDER.index(k) for k in hits[v]), v))
            return self.review(cand, [(v, 1.0) for v in ranked], 1.0, "keys")
        if hits:
            (vid, kinds), = hits.items()
            score = 0.9 if set(kinds) == {"call_sign"} else 1.0
            if score >= self.config.auto_merge:
                return self.assign(cand, self.vessels[vid], score)
            return self.review(cand, [(vid, score)], score, "call-sign")
        scored = sorted(((-s, v) for v in self.vessels if (s := self.score(cand, self.vessels[v])) is not None))
        top = [(v, round(-s, 4)) for s, v in scored[:2]]
        if top and top[0][1] >= self.config.auto_merge:
            return self.assign(cand, self.vessels[top[0][0]], top[0][1])
        if top and top[0][1] >= self.config.review_min:
            return self.review(cand, top, top[0][1], "fuzzy")
        self.create(cand)

    def follow(self, cand: _Cand, review: Mapping[str, Any]) -> None:
        decision = review.get("decision") or {}
        action = decision.get("action")
        if review.get("status") == "decided" and action == "same-vessel" and decision.get("vessel_id") in self.vessels:
            return self.assign(cand, self.vessels[decision["vessel_id"]], 1.0)
        if review.get("status") == "decided" and action == "new-vessel":
            return self.create(cand)
        self.assignments[cand.fp] = None
        self.skipped.append({"fingerprint": cand.fp, "reason": f"merge review {review['id']} {review.get('status')}"
                             + (f" ({action})" if action else "")})

    def key_hits(self, cand: _Cand) -> dict[str, list[str]]:
        hits: dict[str, list[str]] = {}
        for kind, value in cand.keys.items():
            for vid in sorted(self.index.get((kind, value), ())):
                hits.setdefault(vid, []).append(kind)
        for vid, kinds in list(hits.items()):
            if set(kinds) == {"call_sign"} and self.conflicts(cand, self.vessels[vid]):
                del hits[vid]  # a reissued call sign: the vessel holds another boat's keys
        return hits

    @staticmethod
    def conflicts(cand: _Cand, vessel: _Vessel) -> bool:
        return any(kind in vessel.keys and vessel.keys[kind] != value for kind, value in cand.keys.items())

    def score(self, cand: _Cand, vessel: _Vessel) -> float | None:
        if self.conflicts(cand, vessel):
            return None
        if cand.norm == vessel.norm or cand.norm in vessel.aliases:
            name = 1.0
        else:
            name = max([name_similarity(cand.norm, vessel.norm)] + [name_similarity(cand.norm, a) for a in vessel.aliases])
        if name < NAME_MIN:
            return None  # port, landing and length alone never make two boats one

        def same(a, b):
            return 0.5 if a is None or b is None else float(a == b)

        length = 0.5 if not cand.length or not vessel.length else float(
            abs(cand.length - vessel.length) <= 0.1 * max(cand.length, vessel.length))
        return 0.55 * name + 0.25 * same(cand.port, vessel.port) + 0.10 * same(cand.landing, vessel.landing) + 0.10 * length

    def assign(self, cand: _Cand, vessel: _Vessel, score: float) -> None:
        vessel.cands.append((cand, score))
        self._learn(vessel, cand)
        self.assignments[cand.fp] = vessel.id
        self.scores[cand.fp] = score

    def review(self, cand: _Cand, proposals: list, score: float, basis: str) -> None:
        candidate = {"fingerprint": cand.fp, "source_id": cand.raw.source_id, "name": cand.name, "name_norm": cand.norm,
                     "port_id": cand.port, "landing_id": cand.landing, "keys": cand.keys, "source_url": cand.url}
        proposal = {"vessel_id": proposals[0][0], "basis": basis,
                    "vessels": [{"vessel_id": v, "name": self.vessels[v].name, "score": s} for v, s in proposals]}
        op = {"op": "review.open", "kind": "merge", "fingerprint": cand.fp, "candidate_json": candidate,
              "proposal_json": proposal, "score": round(score, 4), "opened_at": self.now}
        self.ops.append(op)
        self.review_ids.append(ops.review_id("merge", cand.fp))
        self.assignments[cand.fp] = None

    def create(self, cand: _Cand) -> None:
        kind = next((k for k in KEY_ORDER if k in cand.keys), None)
        key = (f"{KEY_PREFIX[kind]}:{cand.keys[kind]}" if kind
               else f"name-port:{slugify(cand.name)}|{cand.port or '-'}")
        if ops.vessel_id(self.config.region, key) in self.vessels:
            key += "~" + ops.sha256(cand.fp)[:8]
        vid = ops.vessel_id(self.config.region, key)
        vessel = _Vessel(vid, self.new_slug(cand), cand.name, cand.norm, {}, None, None, None, {}, frozenset(), None, key)
        self._add(vessel)
        self.created.append(vid)
        self.assign(cand, vessel, 1.0)

    def new_slug(self, cand: _Cand) -> str:
        base = slugify(cand.name)

        def fit(*suffix: str) -> str:  # at most SLUG_MAX characters: the base gives way to the suffix
            tail = "".join(f"-{part}" for part in suffix)
            return base[:SLUG_MAX - len(tail)].strip("-") + tail

        options = [fit()] + ([fit(cand.port)] if cand.port else [])
        slug = next((s for s in options if s not in self.slugs), None)
        number = 2
        while slug is None:
            trial = fit(*([cand.port] if cand.port else []), str(number))
            slug = trial if trial not in self.slugs else None
            number += 1
        self.slugs.add(slug)
        return slug

    # -- columns and operations

    def facts_for(self, vessel: _Vessel) -> tuple[list[_Fact], list[_Fact]]:
        """(every current fact, this run's facts) for a vessel; this run's replace a source's stored ones per field."""
        fresh: dict[str, _Fact] = {}
        for facts, fp in [(c.facts, c.fp) for c, _score in vessel.cands] + [(vessel.extra, vessel.id)]:
            for fact in facts:
                key = ops.value_key(fact.value) if _json_ok(fact.value) else None
                if key is None:
                    self.skipped.append({"fingerprint": fp, "reason": f"fact {fact.field}: not JSON"})
                    continue
                ident = ops.fact_id(vessel.id, fact.field, fact.source_id, fact.source_url, key)
                fresh[ident] = _Fact(ident, fact.field, fact.value, fact.source_id, fact.source_url, fact.method,
                                     float(fact.confidence), fact.rights, fact.retrieved_at, key)
        reported = {(f.field, f.source_id) for f in fresh.values()}
        stored = [f for f in self.stored_facts.get(vessel.id, ()) if (f.field, f.source_id) not in reported
                  and f.id not in fresh]
        return stored + sorted(fresh.values(), key=lambda f: f.id), sorted(fresh.values(), key=lambda f: f.id)

    def emit(self, vessel: _Vessel) -> None:
        facts, fresh = self.facts_for(vessel)
        by_field: dict[str, list[_Fact]] = {}
        for fact in facts:
            if fact.value is None and fact.source_id != "admin":
                continue  # only an admin's null is "no value"; anyone else's null is no fact
            by_field.setdefault(fact.field, []).append(fact)
        pinned = vessel.pinned
        stored = vessel.stored or {}
        cols: dict[str, Any] = {}
        winners: dict[str, _Fact] = {}
        for field_, col in COLUMNS.items():
            rule = self.config.rules.get(field_)
            best = winner(by_field.get(field_, ()), rule) if rule else None
            if best is None or best.value is STORED:
                continue  # no fact, or the stored winner keeps the stored value
            ok, value = _column_value(col, best.value)
            if ok:
                cols[col], winners[col] = value, best
        rule = self.config.rules.get("operator")
        best = winner(by_field.get("operator", ()), rule) if rule else None
        if (best is not None and isinstance(best.value, str) and name_norm(best.value)
                and not {"*", "operator_id"} & vessel.pinned):
            cols["operator_id"] = self.operator(best.value.strip()[:120].strip())
        if vessel.stored is None:  # a new vessel: candidate hints fill what no fact gave
            for kind in KEY_ORDER:
                if kind not in cols and kind in vessel.keys and _column_value(kind, vessel.keys[kind])[0]:
                    cols[kind] = vessel.keys[kind]
            cols.setdefault("port_id", vessel.port)
            cols.setdefault("landing_id", vessel.landing)
        status = None
        scope_rule = self.config.rules.get("scope")
        scope = winner(by_field.get("scope", ()), scope_rule) if scope_rule else None
        if scope is not None and isinstance(scope.value, Mapping) and isinstance(scope.value.get("in_scope"), bool):
            if not scope.value["in_scope"]:
                status = "excluded"
            elif stored.get("status") == "excluded":
                status = "active"

        old_name, old_norm = (stored.get("name"), stored.get("name_norm")) if vessel.stored else (None, None)
        name = cols.pop("name", None)
        if "*" in pinned or "name" in pinned or "name_norm" in pinned or not name or not name_norm(name):
            name = old_name or self.best_name(vessel)
        norm = old_norm if vessel.stored and name == old_name else name_norm(name)
        cols = {c: v for c, v in cols.items() if "*" not in pinned and c not in pinned}

        op = {"op": "vessel.upsert", "id": vessel.id, "slug": vessel.slug, "name": name, "name_norm": norm, **cols}
        if vessel.stored is None:
            op.update(creation_key=vessel.creation_key, status=status or "active", profile_status="hidden",
                      first_seen_at=self.now)
        else:
            op["first_seen_at"] = ops.iso(stored["first_seen_at"], "first_seen_at")
            if status and "status" not in pinned and "*" not in pinned and status != stored.get("status"):
                op["status"] = status
        merged = {**{c: stored.get("waters" if c == "waters_json" else c) for c in TARGET}, **cols}
        op["completeness"] = round(sum(merged.get(c) not in (None, [], "") for c in TARGET) / len(TARGET), 4)
        op["last_seen_at"] = self.now
        self.ops.append({k: op[k] for k in sorted(op)})

        if vessel.stored is not None and norm != old_norm:
            source = winners.get("name")
            url = source.source_url if source and ops.https_url(source.source_url) else self.alias_url(vessel)
            if url:
                self.alias(vessel, old_name, old_norm, "former-name", url)
            self.ops.append({"op": "change.record", "vessel_id": vessel.id, "kind": "renamed",
                             "before_json": {"name": old_name}, "after_json": {"name": name}, "detected_at": self.now})
            vessel.aliases.pop(norm, None)
        for cand, _score in sorted(vessel.cands, key=lambda c: c[0].fp):
            if cand.norm != norm and cand.url:
                self.alias(vessel, cand.name, cand.norm, ALIAS_KIND.get(cand.raw.source_id, "spelling"), cand.url)
        self.class_review(vessel, by_field.get("vessel_class", ()), winners.get("vessel_class"))
        for fact in fresh:
            self.fact(vessel, fact)

    def operator(self, name: str) -> str:
        """The operator id for an entity name: the stored one of that normalised name, else a new one (sent)."""
        norm = name_norm(name)
        if norm not in self.operators:
            ident = ops.id32(self.config.region, "operator", norm)
            slug, number = slugify(name) or "operator", 2
            while slug in self.operator_slugs:
                slug, number = f"{slugify(name) or 'operator'}-{number}", number + 1
            self.operators[norm] = ident
            self.operator_slugs.add(slug)
            self.ops.append({"op": "operator.upsert", "id": ident, "slug": slug, "name": name, "seen_at": self.now})
        return self.operators[norm]

    def best_name(self, vessel: _Vessel) -> str:
        rule = self.config.rules.get("name")
        ranked = sorted(vessel.cands, key=lambda c: (
            rule.priority.index(c[0].raw.source_id) if rule and c[0].raw.source_id in rule.priority else 99, c[0].fp))
        return ranked[0][0].name if ranked else vessel.name

    def alias_url(self, vessel: _Vessel) -> str | None:
        urls = sorted(c.url for c, _s in vessel.cands if c.url)
        return urls[0] if urls else None

    def alias(self, vessel: _Vessel, alias: str, norm: str, kind: str, url: str) -> None:
        if not norm or norm in vessel.aliases or not ops.NORM.match(norm):
            return
        vessel.aliases[norm] = {"alias": alias, "alias_norm": norm, "kind": kind}
        self.ops.append({"op": "alias.upsert", "vessel_id": vessel.id, "alias": alias[:120].strip(), "alias_norm": norm,
                         "kind": kind, "source_url": url, "first_seen_at": self.now, "last_seen_at": self.now})

    def class_review(self, vessel: _Vessel, facts: Iterable[_Fact], best: _Fact | None) -> None:
        if "vessel_class" in vessel.pinned or "*" in vessel.pinned:
            return
        strong = sorted((f for f in facts if f.source_id != "admin" and f.confidence >= CLASS_REVIEW_MIN
                         and f.value in ops.ENUMS["vessel_class"]), key=lambda f: (f.source_id, f.value, f.id))
        values = sorted({f.value for f in strong})
        if len(values) < 2 or len({f.source_id for f in strong}) < 2:
            return
        print_ = f"{vessel.id}|{','.join(values)}"
        if ops.review_id("class", print_) in self.decided:
            return
        self.ops.append({"op": "review.open", "kind": "class", "fingerprint": print_, "subject_id": vessel.id,
                         "candidate_json": {"values": [{"source_id": f.source_id, "value": f.value,
                                                        "confidence": f.confidence, "source_url": f.source_url}
                                                       for f in strong]},
                         "proposal_json": {"vessel_id": vessel.id, "vessel_class": best.value if best else None},
                         "score": None, "opened_at": self.now})
        self.review_ids.append(ops.review_id("class", print_))

    def fact(self, vessel: _Vessel, fact: _Fact) -> None:
        op = {"op": "fact.upsert", "vessel_id": vessel.id, "field": fact.field, "value_json": fact.value,
              "source_id": fact.source_id, "source_url": fact.source_url, "method": fact.method,
              "confidence": fact.confidence, "rights": fact.rights, "retrieved_at": fact.retrieved_at}
        try:
            ops.validate_op(op, 0, self.config.region)
        except ops.OpError as error:
            self.skipped.append({"fingerprint": f"{vessel.id}|{fact.field}|{fact.source_id}",
                                 "reason": f"fact: {error}"})
            return
        self.ops.append(op)


def _json_ok(value: Any) -> bool:
    try:
        ops.canonical_json(value)
    except (TypeError, ValueError):
        return False
    return True


ORDER = {kind: i for i, kind in enumerate(ops.OP_KINDS)}


def op_sort_key(op: dict) -> tuple:
    """The order a sink gets operations in: by kind (operators before vessels, offerings before departures), then id."""
    kind = op["op"]
    ident = op.get("id") or op.get("vessel_id", "")
    return ORDER[kind], ident, op.get("field", ""), op.get("source_id", ""), op.get("source_url", ""), \
        op.get("alias_norm", ""), op.get("fingerprint", ""), op.get("kind", ""), ops.canonical_json(op)


def resolve(snapshot: Snapshot, candidates: Iterable[Candidate], config: ResolverConfig, now: str,
            extra_facts: Mapping[str, Iterable[Fact]] | None = None) -> Resolution:
    """Resolve ``candidates`` against ``snapshot``; the operations for a sink and what was decided per candidate."""
    resolver = _Resolver(snapshot, config, now)
    prepared = [c for raw in candidates if (c := resolver.prepare(raw)) is not None]
    for cand in sorted(prepared, key=_Resolver.order):
        resolver.run(cand)
    for vid, facts in sorted((extra_facts or {}).items()):
        vessel = resolver.vessels.get(vid)
        if vessel is None or not vessel.cands:  # only a vessel listed in this run is upserted
            resolver.skipped.append({"fingerprint": vid, "reason": "extra facts: vessel not listed in this run"})
            continue
        vessel.extra = [Fact(f.field, _normal_value(f.field, f.value, config), f.source_id, f.source_url, f.method,
                             f.confidence, f.rights, f.retrieved_at) for f in facts]
    for vid in sorted(resolver.vessels):
        if resolver.vessels[vid].cands:
            resolver.emit(resolver.vessels[vid])
    unique: dict[str, dict] = {}
    for op in resolver.ops:
        unique.setdefault(ops.canonical_json(op), op)
    return Resolution(sorted(unique.values(), key=op_sort_key), dict(sorted(resolver.assignments.items())),
                      dict(sorted(resolver.scores.items())),
                      sorted(resolver.created), sorted(set(resolver.review_ids)), resolver.skipped)

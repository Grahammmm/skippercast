"""Registry operations: ids, canonical JSON and field validation (design section 9, "Operation contract").

A Python mirror of ``server/fleet/ids.ts`` and the field checks in
``server/fleet/registry.ts`` (the reference implementation), so the pipeline
computes the same ids and rejects the same operations as the Worker before it
sends them, and the SqliteSink stores what the Worker would store.
``tests/test_fleet_sink_parity.mjs`` runs both on the same operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Callable
from urllib.parse import urlsplit

OP_KINDS = ("operator.upsert", "vessel.upsert", "fact.upsert", "alias.upsert", "offering.upsert",
            "departure.upsert", "review.open", "change.record", "run.record", "fact.purge")
# Sources whose facts expire under their terms (design section 5, Retention): the only ones fact.purge may delete.
PURGEABLE_SOURCES = ("google-places",)
MAX_KEEP_FIELDS = 20
MAX_OPS = 500
MAX_ERRORS = 50
MAX_SUPERSEDES = 20
MAX_JSON = 16000

ENUMS = {
    "vessel_class": ("six-pack", "inspected-party", "long-range"),
    "waters": ("ocean", "bay", "delta", "inland"),
    "vessel_status": ("active", "inactive", "sold", "excluded"),
    "profile_status": ("listed", "hidden"),
    "method": ("page", "api", "search", "inference", "registry", "ais", "operator"),  # 'admin' is the admin API's alone
    "rights": ("public-domain", "facts-only", "api-terms", "public-record", "noaa-planning-only", "internal-only"),
    "alias_kind": ("former-name", "spelling", "ais-name", "report-name"),
    "trip_type": ("half-day", "three-quarter-day", "full-day", "overnight", "multi-day", "private-charter", "other"),
    "price_basis": ("per-person", "private"),
    "offering_status": ("active", "retired"),
    "days": ("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
    "review_kind": ("merge", "mmsi", "class", "fact-conflict", "change", "vanished", "advisor-link", "scope"),
    "change_kind": ("new", "renamed", "sold", "moved", "vanished", "returned", "price", "schedule", "mmsi", "class"),
    "run_status": ("running", "ok", "failed", "partial"),
    "sink": ("worker", "staging"),
}


def _re(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.ASCII)


HEX32, OPERATOR_ID, SLUG = _re(r"^[0-9a-f]{32}$"), _re(r"^[A-Za-z0-9_-]{16,64}$"), _re(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KEY, NORM = _re(r"^[a-z0-9][a-z0-9-]{0,63}$"), _re(r"^[A-Z0-9]{1,120}$")
FIELD = _re(r"^[a-z][a-z0-9_]*(?:\[\])?(?:\.[a-z][a-z0-9_]*(?:\[\])?){0,5}$")
SPECIES = _re(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ISO = _re(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$")
DATE = _re(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
HHMM, MMDD = _re(r"^(?:[01]\d|2[0-3]):[0-5]\d$"), _re(r"^(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
E164 = _re(r"^\+[1-9]\d{6,14}$")
EMAIL = _re(r'^[^\s@<>()",;:]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
REGION, RUN_ID = _re(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$"), _re(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


# ---- canonical JSON and ids (server/fleet/ids.ts) ------------------------------------

def plain(value: Any) -> Any:
    """Integral floats as ints, recursively, so JSON text matches JavaScript's number printing."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def id32(*parts: str) -> str:
    return sha256("|".join(parts))[:32]


def vessel_id(region: str, creation_key: str) -> str:
    return sha256(f"{region}:{creation_key}")[:32]


def value_key(value: Any) -> str:
    return sha256(canonical_json(value))[:16]


def fact_id(vessel: str, field_: str, source_id: str, source_url: str, key: str) -> str:
    return id32(vessel, field_, source_id, source_url, key)


def offering_id(vessel: str, name_norm: str, season: str) -> str:
    return id32(vessel, name_norm, season)


def departure_id(offering: str, date: str, departs: str) -> str:
    return id32(offering, date, departs)


def review_id(kind: str, fingerprint: str) -> str:
    return id32(kind, fingerprint)


def change_id(vessel: str, kind: str, after_json: str) -> str:
    return id32(vessel, kind, after_json)


def iso_ms(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# ---- field checks (registry.ts SPECS): each returns the stored value or raises OpError ---------

class OpError(ValueError):
    pass


Check = Callable[[Any, str], Any]


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def nullable(check: Check) -> Check:
    def run(v, name):
        return None if v is None else check(v, name)
    run.iso = getattr(check, "iso", False)
    return run


def text(limit: int, pattern: re.Pattern | None = None) -> Check:
    def run(v, name):
        if isinstance(v, str) and 0 < len(v) <= limit and v.strip() == v and (not pattern or pattern.search(v)):
            return v
        raise OpError(f"{name}: invalid")
    return run


def one_of(values) -> Check:
    def run(v, name):
        if isinstance(v, str) and v in values:
            return v
        raise OpError(f"{name}: not one of {', '.join(values)}")
    return run


def integer(lo: int, hi: int) -> Check:
    def run(v, name):
        if _number(v) and float(v).is_integer() and lo <= v <= hi:
            return int(v)
        raise OpError(f"{name}: not an integer in {lo}-{hi}")
    return run


def real(lo: float, hi: float) -> Check:
    def run(v, name):
        if _number(v) and lo <= v <= hi:
            return plain(v)
        raise OpError(f"{name}: not a number in {lo:g}-{hi:g}")
    return run


def iso(v: Any, name: str) -> str:
    match = ISO.match(v) if isinstance(v, str) else None
    try:
        if match:
            parts = [int(x) for x in match.groups()[:6]]
            ms = int(((match.group(7) or "") + "000")[:3])
            return iso_ms(datetime(*parts, ms * 1000, tzinfo=timezone.utc))
    except ValueError:
        pass
    raise OpError(f"{name}: not an ISO-8601 UTC time")


iso.iso = True


def date(v: Any, name: str) -> str:
    try:
        if isinstance(v, str) and DATE.match(v) and datetime.strptime(v, "%Y-%m-%d"):
            return v
    except ValueError:
        pass
    raise OpError(f"{name}: not a YYYY-MM-DD date")


def https_url(v: Any) -> str | None:
    if not isinstance(v, str) or len(v) > 2048 or any(c.isspace() for c in v):
        return None
    try:
        parts = urlsplit(v)
        host = parts.hostname or ""
    except ValueError:
        return None
    return v if parts.scheme == "https" and not parts.username and not parts.password and "." in host else None


def https(v: Any, name: str) -> str:
    url = https_url(v)
    if url is None:
        raise OpError(f"{name}: not an https URL")
    return url


def provenance(v: Any, name: str) -> str:
    if isinstance(v, str) and v.startswith("admin:"):
        raise OpError(f"{name}: admin provenance is written only by the admin API")
    return https(v, name)


def as_json(shape: Callable[[Any, str], None] = lambda v, name: None) -> Check:
    def run(v, name):
        shape(v, name)
        try:
            out = canonical_json(v)
        except (TypeError, ValueError):
            raise OpError(f"{name}: not JSON") from None
        if len(out) > MAX_JSON:
            raise OpError(f"{name}: too large")
        return out
    return run


def list_of(item: Callable[[Any], bool], limit: int) -> Callable[[Any, str], None]:
    def run(v, name):
        if not isinstance(v, list) or len(v) > limit or not all(item(x) for x in v) or len(set(map(repr, v))) != len(v):
            raise OpError(f"{name}: invalid list")
    return run


def obj(v: Any, name: str) -> None:
    if not isinstance(v, dict):
        raise OpError(f"{name}: not an object")


def container(v: Any, name: str) -> None:
    if not isinstance(v, (dict, list)):
        raise OpError(f"{name}: not an object or array")


def matches(pattern: re.Pattern) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, str) and bool(pattern.search(v))


def _not_null(v, name):
    if v is None:
        raise OpError(f"{name}: null is not a value")


IDENT = text(20, _re(r"^[A-Z0-9-]+$"))
SPECS: dict[str, tuple[tuple[str, ...], dict[str, Check]]] = {
    "operator.upsert": (("id", "slug", "name", "seen_at"), {
        "id": text(64, OPERATOR_ID), "seen_at": iso, "slug": text(80, SLUG), "name": text(120),
        "website": nullable(https), "phone_business": nullable(text(16, E164)), "email_business": nullable(text(254, EMAIL)),
        "booking_platform": nullable(text(64, KEY)), "lead_score": nullable(real(0, 100)), "lead_score_json": nullable(as_json(obj))}),
    "vessel.upsert": (("id", "slug", "name", "name_norm", "first_seen_at", "last_seen_at"), {
        "id": text(32, HEX32), "creation_key": text(200, _re(r"^[a-z][a-z0-9-]*:\S+$")), "slug": text(80, SLUG),
        "name": text(120), "name_norm": text(120, NORM), "operator_id": nullable(text(64, OPERATOR_ID)),
        "port_id": nullable(text(64, KEY)), "landing_id": nullable(text(64, KEY)),
        "vessel_class": nullable(one_of(ENUMS["vessel_class"])),
        "waters_json": nullable(as_json(list_of(lambda v: v in ENUMS["waters"], 4))),
        "uscg_doc": nullable(IDENT), "state_reg": nullable(IDENT), "hull_id": nullable(IDENT),
        "call_sign": nullable(text(10, _re(r"^[A-Z0-9]{3,10}$"))), "mmsi": nullable(text(9, _re(r"^\d{9}$"))),
        "year_built": nullable(integer(1850, 2100)), "passengers_max": nullable(integer(0, 2000)),
        "bunks": nullable(integer(0, 500)), "length_ft": nullable(real(1, 500)), "beam_ft": nullable(real(1, 100)),
        "cruise_kn": nullable(real(0, 60)), "website": nullable(https), "booking_url": nullable(https),
        "booking_platform": nullable(text(64, KEY)), "phone_business": nullable(text(16, E164)),
        "email_business": nullable(text(254, EMAIL)), "status": one_of(ENUMS["vessel_status"]),
        "profile_status": one_of(ENUMS["profile_status"]), "completeness": real(0, 1),
        "first_seen_at": iso, "last_seen_at": iso, "last_profiled_at": nullable(iso)}),
    "fact.upsert": (("vessel_id", "field", "value_json", "source_id", "source_url", "method", "confidence", "rights",
                     "retrieved_at"), {
        "id": text(32, HEX32), "vessel_id": text(32, HEX32), "field": text(100, FIELD), "value_json": as_json(_not_null),
        "source_id": text(64, KEY), "source_url": provenance, "method": one_of(ENUMS["method"]),
        "confidence": real(0, 1), "rights": one_of(ENUMS["rights"]), "retrieved_at": iso, "first_seen_at": iso,
        "last_seen_at": iso, "supersedes": as_json(list_of(matches(HEX32), MAX_SUPERSEDES))}),
    "alias.upsert": (("vessel_id", "alias", "alias_norm", "kind", "source_url", "first_seen_at", "last_seen_at"), {
        "vessel_id": text(32, HEX32), "alias": text(120), "alias_norm": text(120, NORM),
        "kind": one_of(ENUMS["alias_kind"]), "source_url": https, "first_seen_at": iso, "last_seen_at": iso}),
    "offering.upsert": (("id", "vessel_id", "name", "trip_type", "seen_at"), {
        "id": text(32, HEX32), "seen_at": iso, "vessel_id": text(32, HEX32), "name": text(120),
        "trip_type": one_of(ENUMS["trip_type"]), "duration_h": nullable(real(0, 720)),
        "price_cents": nullable(integer(0, 10_000_000)), "price_basis": nullable(one_of(ENUMS["price_basis"])),
        "capacity": nullable(integer(1, 2000)), "currency": text(3, _re(r"^[A-Z]{3}$")),
        "departs_local": nullable(text(5, HHMM)), "days_json": nullable(as_json(list_of(lambda v: v in ENUMS["days"], 7))),
        "season_from": nullable(text(5, MMDD)), "season_to": nullable(text(5, MMDD)),
        "target_species_json": nullable(as_json(list_of(matches(SPECIES), 50))), "booking_url": nullable(https),
        "status": one_of(ENUMS["offering_status"]),
        "source_fact_ids_json": nullable(as_json(list_of(matches(HEX32), 100))),
        "valid_from": nullable(date), "valid_to": nullable(date)}),
    "departure.upsert": (("offering_id", "vessel_id", "date", "source_url", "retrieved_at"), {
        "id": text(32, HEX32), "offering_id": text(32, HEX32), "vessel_id": text(32, HEX32), "date": date,
        "departs_local": nullable(text(5, HHMM)), "price_cents": nullable(integer(0, 10_000_000)),
        "load_text": nullable(text(200)), "source_url": https, "retrieved_at": iso}),
    "review.open": (("kind", "fingerprint", "opened_at"), {
        "id": text(32, HEX32), "kind": one_of(ENUMS["review_kind"]), "fingerprint": text(500),
        "subject_id": nullable(text(64, _re(r"^[A-Za-z0-9_-]+$"))), "candidate_json": nullable(as_json(container)),
        "proposal_json": nullable(as_json(container)), "score": nullable(real(0, 1)), "opened_at": iso}),
    "change.record": (("vessel_id", "kind", "after_json", "detected_at"), {
        "id": text(32, HEX32), "vessel_id": text(32, HEX32), "kind": one_of(ENUMS["change_kind"]),
        "before_json": as_json(), "after_json": as_json(), "detected_at": iso, "review_id": nullable(text(32, HEX32))}),
    "run.record": (("step", "sink", "started_at", "status"), {
        "step": text(32, _re(r"^[a-z][a-z-]*$")), "sink": one_of(ENUMS["sink"]), "started_at": iso,
        "finished_at": nullable(iso), "status": one_of(ENUMS["run_status"]), "counts_json": nullable(as_json(obj)),
        "error": nullable(text(2000))}),
    "fact.purge": (("source_id", "keep_fields", "seen_before"), {
        "source_id": one_of(PURGEABLE_SOURCES), "keep_fields": as_json(list_of(matches(FIELD), MAX_KEEP_FIELDS)),
        "seen_before": iso}),
}


@dataclass
class Row:
    kind: str
    index: int
    id: str
    cols: dict
    supersedes: list = field(default_factory=list)


def validate_op(raw: Any, index: int, region: str) -> Row:
    """Field-level validation of one operation (no database), as registry.ts validateOp."""
    if not isinstance(raw, dict):
        raise OpError("not an object")
    rest = dict(raw)
    kind = rest.pop("op", None)
    if kind not in OP_KINDS:
        raise OpError(f"op: not one of {', '.join(OP_KINDS)}")
    required, fields = SPECS[kind]
    for key in rest:
        if key not in fields:
            raise OpError(f"{key}: not a field of {kind}")
    for key in required:
        if key not in rest:
            raise OpError(f"{key}: missing")
    cols = {key: fields[key](value, key) for key, value in rest.items()}
    given = cols.get("id")

    def derived(ident: str) -> str:
        if given is not None and given != ident:
            raise OpError(f"id: does not match the derived id {ident}")
        return ident

    supersedes: list = []
    if kind == "vessel.upsert":
        if "creation_key" in cols and vessel_id(region, cols.pop("creation_key")) != given:
            raise OpError("id: does not match sha256(region:creation_key)")
    elif kind == "fact.upsert":
        key = sha256(cols["value_json"])[:16]
        cols["id"] = derived(fact_id(cols["vessel_id"], cols["field"], cols["source_id"], cols["source_url"], key))
        cols["value_key"] = key
        cols.setdefault("first_seen_at", cols["retrieved_at"])
        cols.setdefault("last_seen_at", cols["retrieved_at"])
        supersedes = json.loads(cols.pop("supersedes", "[]"))
        if cols["id"] in supersedes:
            raise OpError("supersedes: a fact cannot supersede itself")
    elif kind == "departure.upsert":
        cols["id"] = derived(departure_id(cols["offering_id"], cols["date"], cols.get("departs_local") or ""))
    elif kind == "review.open":
        cols["id"] = derived(review_id(cols["kind"], cols.pop("fingerprint")))
    elif kind == "change.record":
        cols["id"] = derived(change_id(cols["vessel_id"], cols["kind"], cols["after_json"]))
    elif kind in ("operator.upsert", "offering.upsert"):
        cols["updated_at"] = cols.pop("seen_at")
    if "first_seen_at" in cols and cols["first_seen_at"] > cols["last_seen_at"]:
        raise OpError("first_seen_at: after last_seen_at")
    ident = {"alias.upsert": lambda: f"{cols['vessel_id']}|{cols['alias_norm']}",
             "run.record": lambda: cols["step"],
             "fact.purge": lambda: f"{cols['source_id']}|{cols['seen_before']}|{cols['keep_fields']}"}.get(kind, lambda: cols["id"])()
    return Row(kind, index, ident, cols, supersedes)


def validate_ops(ops: list, region: str) -> tuple[list[Row], list[dict]]:
    """Every operation's fields; (rows, errors) with at most MAX_ERRORS errors, by index."""
    rows, errors = [], []
    for index, raw in enumerate(ops):
        try:
            rows.append(validate_op(raw, index, region))
        except OpError as error:
            if len(errors) < MAX_ERRORS:
                op = raw.get("op") if isinstance(raw, dict) else None
                errors.append({"index": index, "op": op if isinstance(op, str) else None, "error": str(error)})
    return rows, errors


def wire(op: dict) -> dict:
    """An operation as the WorkerSink sends it: integral floats as ints, timestamps with milliseconds."""
    out = plain(op)
    _required, fields = SPECS.get(op.get("op"), ((), {}))
    for key, value in out.items():
        if getattr(fields.get(key), "iso", False) and value is not None:
            out[key] = iso(value, key)
    return out

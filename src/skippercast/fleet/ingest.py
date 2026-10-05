"""The discover, resolve and ingest steps (design sections 4, 6, 7 and 9).

- ``discover`` runs the adapter of every enabled discovery binding and writes
  ``candidates.jsonl`` and ``discover.json`` (per binding: a count, a skip or the
  error; ``complete`` when no binding failed, which ``refresh`` needs before it
  counts an unlisted vessel towards ``vanished``). One failing source does not
  stop the others.
- ``resolve`` resolves the candidates (and a file import's ``imported.jsonl``)
  against the registry snapshot and writes ``resolved.jsonl``, the vessels
  enrich-code works on.
- ``ingest`` turns everything into registry operations and sends them to the
  sink: it resolves again with the enrich-code facts (``facts.jsonl``) so they
  can win columns, adds the offerings and departures of every assigned
  candidate, and applies the supersede rule: a ``fact.upsert`` of a scalar field
  supersedes the current facts of the same vessel, field and source that this
  run did not report (from the staging snapshot's facts or the Worker's
  winning-source record). A flagged fact (a webmail address) is held back and
  opens a ``fact-conflict`` review until an admin confirms it. It writes
  ``ingest-ops.jsonl`` and ``ingest-snapshot.json`` (the registry before the
  write) for ``refresh``. On the staging sink every stored fact must have a
  ``source_url``, or the step fails.
- ``ingest --profiles DIR`` (CF-20) ingests the OSINT agent's profiles instead:
  each file is validated (``profile.validate_profile``: schema and policy) and
  must name a vessel of this region; invalid files are refused and listed in
  ``profiles-ingest.json``, valid ones become ``osint`` facts, offerings and
  ``fact-conflict`` reviews (``profile_ops``).

The snapshot comes from the sink: ``Snapshot.from_sqlite`` for the staging
sink, ``GET /api/fleet/jobs/snapshot`` (paged, OIDC) for the Worker.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request

from . import ops, profile
from .adapters import Candidate, Departure, Fact, Offering, RunContext, get
from .adapters.base import offering_name_norm
from .enrich import ENRICHERS, IMPORTERS
from .resolve import ORDER, ResolverConfig, Snapshot, fingerprint, op_sort_key, resolve
from .sinks import SinkError

Loader = Callable[[Any, str], Snapshot]
NOT_DISCOVERY = frozenset({*ENRICHERS, *IMPORTERS})  # enrich-code runs these


# ---- snapshot ----------------------------------------------------------------------------

def load_snapshot(sink, region: str) -> Snapshot:
    """The registry as the sink holds it: staging facts included; the Worker's pages (no fact values)."""
    if getattr(sink, "db", None) is not None:
        return Snapshot.from_sqlite(sink.db, region)
    pages, cursor = [], ""
    while len(pages) < 10_000:
        query = urlencode({"region": region, **({"cursor": cursor} if cursor else {})})
        request = Request(f"{sink.base}/api/fleet/jobs/snapshot?{query}", headers={
            "Authorization": "Bearer " + sink.token(), "Accept": "application/json", "User-Agent": sink.user_agent})
        with sink.opener(request, timeout=60) as response:
            pages.append(json.load(response))
        cursor = pages[-1].get("next")
        if not cursor:
            return Snapshot.from_pages(pages)
    raise SinkError("snapshot: more than 10000 pages")


def snapshot_to_dict(snapshot: Snapshot) -> dict:
    return {**asdict(snapshot), "advisor_slugs": sorted(snapshot.advisor_slugs)}


def snapshot_from_dict(doc: Mapping[str, Any]) -> Snapshot:
    return Snapshot(list(doc["vessels"]), list(doc["reviews"]), list(doc["operators"]),
                    frozenset(doc["advisor_slugs"]), doc["facts"])


# ---- adapter output from the run directory ------------------------------------------------

def fact_from_dict(d: Mapping[str, Any]) -> Fact:
    return Fact(d["field"], d["value"], d["source_id"], d["source_url"], d["method"], d["confidence"], d["rights"],
                d["retrieved_at"], tuple(d.get("flags") or ()))


def _offering(d: Mapping[str, Any]) -> Offering:
    return Offering(d["name"], d["trip_type"], tuple(fact_from_dict(f) for f in d["facts"]), d.get("price_cents"),
                    d.get("price_basis"), d.get("currency") or "USD", d.get("duration_h"), d.get("capacity"),
                    d.get("departs_local"), tuple(d["days"]) if d.get("days") is not None else None,
                    d.get("season_from"), d.get("season_to"))


def candidate_from_dict(d: Mapping[str, Any]) -> Candidate:
    return Candidate(d["source_id"], d["name"], d.get("port_hint"), d.get("landing_hint"), dict(d.get("keys") or {}),
                     tuple(fact_from_dict(f) for f in d.get("facts") or ()), d.get("record_id"),
                     tuple(_offering(o) for o in d.get("offerings") or ()),
                     tuple(Departure(_offering(x["offering"]), x["date"], x.get("departs_local"), x.get("price_cents"),
                                     x.get("load_text"), x["source_url"], x["retrieved_at"])
                           for x in d.get("departures") or ()))


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    rows = list(rows)
    path.write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return len(rows)


def run_candidates(run_dir: Path) -> list[Candidate]:
    return [candidate_from_dict(d) for name in ("candidates.jsonl", "imported.jsonl") for d in _jsonl(run_dir / name)]


# ---- steps -------------------------------------------------------------------------------

def discover(ctx: RunContext, sink, adapters: Mapping[str, Any] | None = None) -> dict:
    adapters, rows, report = dict(adapters or {}), [], {}
    for binding in ctx.region.enabled_sources():
        if binding.adapter in NOT_DISCOVERY:
            continue
        try:
            adapter = adapters.get(binding.adapter) or get(binding.adapter)()
        except NotImplementedError as error:
            report[binding.id] = {"status": "skipped", "reason": str(error)}
            continue
        if getattr(adapter, "kind", "discover") not in ("discover", "both"):
            continue
        try:
            found = [c.as_dict() for c in adapter.discover(binding, ctx)]
        except Exception as error:  # one source failing never stops the others; the run is then partial
            report[binding.id] = {"status": "failed", "error": f"{type(error).__name__}: {error}"[:500]}
            continue
        rows += found
        report[binding.id] = {"status": "ok", "candidates": len(found)}
    failed = sum(r["status"] == "failed" for r in report.values())
    doc = {"at": ops.iso(ctx.clock(), "at"), "complete": not failed, "bindings": report}
    (ctx.run_dir / "discover.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"candidates": write_jsonl(ctx.run_dir / "candidates.jsonl", rows), "bindings": len(report), "failed": failed}


def resolve_step(ctx: RunContext, sink, load: Loader = load_snapshot) -> dict:
    snapshot = load(sink, ctx.region.id)
    result = resolve(snapshot, run_candidates(ctx.run_dir), ResolverConfig.from_region(ctx.region), ctx.clock())
    stored = {v["id"]: v for v in snapshot.vessels}
    places = {f["vessel_id"]: f["value"] for f in sorted(snapshot.facts or (), key=lambda f: f["retrieved_at"])
              if f["field"] == "place_id" and isinstance(f.get("value"), str)}
    vessels = []
    for op in result.ops:
        if op["op"] == "vessel.upsert":
            old = stored.get(op["id"], {})
            row = {"vessel_id": op["id"], "name": op["name"], "port_id": op.get("port_id", old.get("port_id")),
                   "website": op.get("website", old.get("website"))}
            vessels.append({**row, **({"place_id": places[op["id"]]} if op["id"] in places else {})})
    return {"vessels": write_jsonl(ctx.run_dir / "resolved.jsonl", vessels), "created": len(result.created),
            "reviews": len(result.reviews), "skipped": len(result.skipped)}


def _held_fact(row: Mapping[str, Any], fact: Fact, decided: Mapping[str, Mapping], now: str) -> tuple[bool, dict | None]:
    """(keep, review op) for a flagged fact: kept once an admin confirmed it; else held with a fact-conflict review."""
    print_ = f"{row['vessel_id']}|{fact.field}|{fact.source_id}|{ops.value_key(fact.value)}"
    review = decided.get(ops.review_id("fact-conflict", print_))
    if review is not None:
        return review.get("status") == "decided" and (review.get("decision") or {}).get("action") == "confirm", None
    return False, {"op": "review.open", "kind": "fact-conflict", "fingerprint": print_, "subject_id": row["vessel_id"],
                   "candidate_json": {"field": fact.field, "value": fact.value, "source_id": fact.source_id,
                                      "source_url": fact.source_url, "flags": list(fact.flags)},
                   "proposal_json": {"vessel_id": row["vessel_id"]}, "score": None, "opened_at": now}


def _supersede(out: list[dict], snapshot: Snapshot, region: str) -> None:
    """Point each scalar fact.upsert at the same source's current facts of that field this run did not report."""
    current: dict[tuple, list] = {}
    if snapshot.facts is not None:
        rows = [(f["vessel_id"], f) for f in snapshot.facts]
    else:
        rows = [(v["id"], s) for v in snapshot.vessels for s in v.get("sources") or ()]
    for vid, f in rows:
        current.setdefault((vid, f["field"], f["source_id"]), []).append((f["id"], ops.iso(f["retrieved_at"], "at")))
    facts = [op for op in out if op["op"] == "fact.upsert"]
    reported = {ops.validate_op(op, 0, region).id for op in facts}
    for op in facts:
        if "[]" in op["field"]:
            continue
        at = ops.iso(op["retrieved_at"], "retrieved_at")
        old = sorted(i for i, seen in current.get((op["vessel_id"], op["field"], op["source_id"]), ())
                     if i not in reported and seen <= at)
        if old:
            op["supersedes"] = old[:ops.MAX_SUPERSEDES]


def build_ops(snapshot: Snapshot, candidates: list[Candidate], fact_rows: list[Mapping[str, Any]],
              config: ResolverConfig, now: str) -> tuple[list[dict], dict]:
    """Every registry operation of one ingest, sorted for the sink, and what was left out."""
    decided = {r["id"]: r for r in snapshot.reviews}
    extra: dict[str, list[Fact]] = {}
    out: list[dict] = []
    held = 0
    for row in fact_rows:
        fact = fact_from_dict(row)
        if fact.flags:
            keep, review = _held_fact(row, fact, decided, now)
            out += [review] if review else []
            if not keep:
                held += 1
                continue
        extra.setdefault(row["vessel_id"], []).append(fact)
    result = resolve(snapshot, candidates, config, now, extra)
    out += result.ops
    skipped = list(result.skipped)
    for cand in candidates:
        vid = result.assignments.get(fingerprint(cand))
        for op in ([o.op(vid, now) for o in cand.offerings] + [d.op(vid) for d in cand.departures]) if vid else ():
            try:
                ops.validate_op(op, 0, config.region)
            except ops.OpError as error:
                skipped.append({"fingerprint": fingerprint(cand), "reason": f"{op['op']}: {error}"})
                continue
            out.append(op)
    unique = {ops.canonical_json(op): op for op in out}
    out = sorted(unique.values(), key=op_sort_key)
    _supersede(out, snapshot, config.region)
    return out, {"held": held, "skipped": skipped, "created": result.created}


# ---- OSINT profiles (``ingest --profiles DIR``, design section 8, CF-20) ---------------------------

def _read_profile(path: Path, region: str, vessels: Mapping[str, Mapping], off_limits,
                  now: str) -> tuple[dict | None, list[str]]:
    """(document, errors): schema and policy (``profile.validate_profile``), its times (valid and not after the
    run clock ``now``), then the region and the vessel."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, [f"{type(error).__name__}: {error}"[:300]]
    errors = profile.validate_profile(doc, off_limits)  # raises MissingDependency without jsonschema: never unvalidated
    errors = errors or profile.time_errors(doc, now)
    if errors:
        return None, errors
    if doc["region"] != region:
        return None, [f"region: {doc['region']} is not this run's region {region}"]
    vessel = vessels.get(doc["vessel_id"])
    if vessel is None:
        return None, [f"vessel_id: no vessel {doc['vessel_id']} in the {region} registry"]
    if ops.removal_requested(vessel):
        return None, ["vessel_id: the operator asked for removal; nothing is added"]
    return doc, []


def profile_ops(snapshot: Snapshot, docs: list[dict], config: ResolverConfig, now: str) -> tuple[list[dict], dict]:
    """The registry operations for valid profiles of known vessels, and what was left out.

    Each profile is an ``osint`` candidate assigned to the vessel it names (a decided ``same-vessel`` merge for
    its fingerprint ``osint|<vessel_id>`` is added to a copy of the snapshot, so resolve never matches it
    elsewhere), so the facts rank under the resolver rules like any other source's and ``build_ops`` applies the
    supersede rule: a missing value supersedes nothing. A profile does not list a vessel: each vessel upsert keeps
    the stored ``last_seen_at`` (``refresh`` counts it towards ``vanished``) and moves ``last_profiled_at``
    forward. Trips become offerings only when the vessel has no offering of that name (deterministic sources own
    prices and schedules; an osint trip never overwrites or duplicates theirs), seen at the profile's time.
    Conflicts open ``fact-conflict`` reviews.
    """
    stored = {v["id"]: v for v in snapshot.vessels}
    mapped = [profile.profile_facts(doc) for doc in docs]
    decisions = [{"id": ops.review_id("merge", f"{profile.SOURCE_ID}|{p.vessel_id}"), "status": "decided",
                  "decision": {"action": "same-vessel", "vessel_id": p.vessel_id}} for p in mapped]
    assigned = Snapshot(snapshot.vessels, list(snapshot.reviews) + decisions, snapshot.operators,
                        snapshot.advisor_slugs, snapshot.facts)
    candidates = [Candidate(profile.SOURCE_ID, stored[p.vessel_id]["name"], facts=tuple(p.facts), record_id=p.vessel_id)
                  for p in mapped]
    flagged = [{"vessel_id": p.vessel_id, **f.as_dict()} for p in mapped for f in p.flagged]
    out, info = build_ops(assigned, candidates, flagged, config, now)
    at = {p.vessel_id: ops.iso(p.profiled_at or now, "profiled_at") for p in mapped}
    for op in out:
        if op["op"] == "vessel.upsert" and op["id"] in at:
            old = stored[op["id"]]
            op["last_seen_at"] = ops.iso(old["last_seen_at"], "last_seen_at")
            previous = old.get("last_profiled_at")
            op["last_profiled_at"] = max(at[op["id"]], ops.iso(previous, "last_profiled_at") if previous else "")
    extra: list[dict] = []
    for p in mapped:
        names = profile.offering_names(stored[p.vessel_id].get("offerings"))
        for offering, species in p.offerings:
            key = offering.id(p.vessel_id)
            if offering_name_norm(offering.name) in names:
                info["skipped"].append({"fingerprint": key, "reason": "offering: the vessel already has this trip"})
                continue
            names.add(offering_name_norm(offering.name))
            op = {**offering.op(p.vessel_id, at[p.vessel_id]), **({"target_species_json": species} if species else {})}
            extra.append(op)
        for conflict in p.conflicts:
            values = conflict.get("values") or []
            print_ = f"{p.vessel_id}|{conflict.get('field')}|{profile.SOURCE_ID}|{ops.value_key(values)}"
            extra.append({"op": "review.open", "kind": "fact-conflict", "fingerprint": print_, "subject_id": p.vessel_id,
                          "candidate_json": {"field": conflict.get("field"), "values": values,
                                             "note": str(conflict.get("note") or "")[:500], "source_id": profile.SOURCE_ID},
                          "proposal_json": {"vessel_id": p.vessel_id}, "score": None, "opened_at": now})
    for op in extra:
        try:
            ops.validate_op(op, 0, config.region)
        except ops.OpError as error:
            info["skipped"].append({"fingerprint": op.get("id") or op.get("fingerprint"), "reason": f"{op['op']}: {error}"})
            continue
        out.append(op)
    return sorted(out, key=op_sort_key), info


def ingest_profiles(ctx: RunContext, sink, profiles: Path | str, load: Loader = load_snapshot, off_limits=None) -> dict:
    """Validate every ``*.json`` in ``profiles``, refuse and list the invalid ones, and ingest the rest.

    One profile per vessel is ingested: when a directory holds several for one vessel, the latest
    (``profile.profiled_at``, then file name) wins and the others are listed as skipped. Writes
    ``profiles-ingest.json`` (files ingested, refused with their errors, skipped) and ``profiles-ops.jsonl``.
    """
    folder = Path(profiles)
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder}: no profiles directory")
    snapshot, now = load(sink, ctx.region.id), ops.iso(ctx.clock(), "now")
    hosts = profile.load_off_limits() if off_limits is None else tuple(off_limits)
    vessels = {v["id"]: v for v in snapshot.vessels}
    refused, skipped, chosen = [], [], {}
    files = sorted(folder.glob("*.json"))
    for path in files:
        doc, errors = _read_profile(path, ctx.region.id, vessels, hosts, now[:19] + "Z")
        if doc is None:
            refused.append({"file": path.name, "errors": errors[:50]})
            continue
        key = (profile.profiled_at(doc) or "", path.name)
        kept = chosen.get(doc["vessel_id"])
        if kept is not None:
            older, newer = sorted([kept, (key, path.name, doc)], key=lambda k: k[0])
            skipped.append({"file": older[1], "reason": f"a newer profile of the same vessel: {newer[1]}"})
            chosen[doc["vessel_id"]] = newer
        else:
            chosen[doc["vessel_id"]] = (key, path.name, doc)
    docs = [entry[2] for _vid, entry in sorted(chosen.items())]
    out, info = profile_ops(snapshot, docs, ResolverConfig.from_region(ctx.region), now) if docs else ([], {"held": 0, "skipped": []})
    write_jsonl(ctx.run_dir / "profiles-ops.jsonl", out)
    result = sink.apply(out) if out else {"ops": 0, "changed": 0, "counts": {}}
    report = {"at": now, "dir": str(folder), "files": len(files), "ingested": sorted(e[1] for e in chosen.values()),
              "refused": refused, "skipped": skipped, "ops_skipped": info["skipped"], "held": info["held"]}
    (ctx.run_dir / "profiles-ingest.json").write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                                      encoding="utf-8")
    kinds = {kind: sum(op["op"] == kind for op in out) for kind in ORDER}
    return {"files": len(files), "ingested": len(chosen), "refused": len(refused), "failed": len(refused),
            "skipped": len(skipped) + len(info["skipped"]), "held": info["held"], "ops": len(out),
            "changed": result["changed"], **{kind.replace(".", "_"): n for kind, n in kinds.items() if n}}


def ingest(ctx: RunContext, sink, load: Loader = load_snapshot, profiles: Path | str | None = None) -> dict:
    if profiles is not None:
        return ingest_profiles(ctx, sink, profiles, load)
    snapshot, now = load(sink, ctx.region.id), ops.iso(ctx.clock(), "now")
    out, info = build_ops(snapshot, run_candidates(ctx.run_dir), _jsonl(ctx.run_dir / "facts.jsonl"),
                          ResolverConfig.from_region(ctx.region), now)
    (ctx.run_dir / "ingest-snapshot.json").write_text(
        json.dumps({"now": now, "snapshot": snapshot_to_dict(snapshot)}, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    write_jsonl(ctx.run_dir / "ingest-ops.jsonl", out)
    result = sink.apply(out) if out else {"ops": 0, "changed": 0, "counts": {}}
    db = getattr(sink, "db", None)
    if db is not None:  # design section 9: every fact in the staging registry has its source
        missing = db.execute("SELECT count(*) FROM fleet_vessel_facts WHERE source_url IS NULL OR trim(source_url)=''").fetchone()[0]
        if missing:
            raise SinkError(f"{missing} stored facts have no source_url")
    kinds = {kind: sum(op["op"] == kind for op in out) for kind in ORDER}
    return {"ops": len(out), "changed": result["changed"], "held": info["held"], "skipped": len(info["skipped"]),
            **{kind.replace(".", "_"): n for kind, n in kinds.items() if n}}


__all__ = ["build_ops", "candidate_from_dict", "discover", "fact_from_dict", "ingest", "ingest_profiles", "load_snapshot",
           "profile_ops", "resolve_step", "run_candidates", "snapshot_from_dict", "snapshot_to_dict", "write_jsonl"]

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

from . import ops
from .adapters import Candidate, Departure, Fact, Offering, RunContext, get
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


def ingest(ctx: RunContext, sink, load: Loader = load_snapshot) -> dict:
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


__all__ = ["build_ops", "candidate_from_dict", "discover", "fact_from_dict", "ingest", "load_snapshot",
           "resolve_step", "run_candidates", "snapshot_from_dict", "snapshot_to_dict", "write_jsonl"]

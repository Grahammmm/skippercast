"""The refresh step: change detection after ingest (design section 9, "Change detection").

It compares the registry before this run's write (``ingest-snapshot.json``)
with the operations ingest sent (``ingest-ops.jsonl``) and sends
``change.record`` operations; ``renamed`` is the resolver's and already went with
ingest.

| Kind | Rule here |
| --- | --- |
| ``new`` | a vessel the snapshot did not hold |
| ``sold`` | ``operator_id`` changed from a stored operator |
| ``moved`` | a stored ``port_id`` or ``landing_id`` changed |
| ``mmsi``, ``class`` | ``mmsi`` changed (also from none: the watch list needs it); a stored ``vessel_class`` changed |
| ``returned`` | listed again after missing a complete discovery run while ``inactive`` or vanished |
| ``vanished`` | ``active``, listed by no source for ``vanished_after_runs`` complete discovery runs and ``vanished_after_days``; opens a ``vanished`` review, the status changes only on the admin's decision |
| ``price`` | an active offering's ``price_cents`` changed |
| ``schedule`` | an offering added or retired, or its ``departs_local`` or ``days`` changed |

Offerings of a vessel whose sources listed offerings in this run, but not that
one, are retired (``offering.upsert`` with ``status: retired``), but only when
every discovery binding of the run succeeded (``discover.json`` ``complete``):
in a ``partial`` run the failed source's offerings are kept, so an outage records
no ``schedule`` change. A vessel is "listed" when a candidate was assigned to it
or proposed for it in a merge review. Runs count towards ``vanished`` only when
the run's discovery was ``complete`` as well, so a source outage never marks
its boats vanished. Change ids hash the after-value, so a rerun records nothing
new.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import ops
from .adapters import RunContext
from .ingest import _jsonl, snapshot_from_dict
from .resolve import Snapshot

WATCHED = (("operator_id", "sold"), ("mmsi", "mmsi"), ("vessel_class", "class"))


def discovery_history(region_dir: Path, exclude: str | None = None) -> list[str]:
    """When each earlier complete discovery run of the region listed its boats (``discover.json`` ``at``)."""
    times = []
    for path in sorted(Path(region_dir).glob("runs/*/discover.json")):
        if path.parent.name == exclude:
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("complete"):
            times.append(ops.iso(doc["at"], "at"))
    return sorted(times)


def _days(later: str, earlier: str) -> float:
    def parse(text):
        return datetime.fromisoformat(ops.iso(text, "at").replace("Z", "+00:00"))
    return (parse(later) - parse(earlier)).total_seconds() / 86400


def detect(before: Snapshot, sent: Iterable[Mapping[str, Any]], now: str, *, complete: bool, history: list[str],
           vanished_runs: int, vanished_days: float) -> list[dict]:
    """The change, review and offering operations for one run (pure; see the module table).

    ``history``: the earlier complete discovery runs; ``complete``: this run's discovery was."""
    sent = list(sent)
    stored = {v["id"]: v for v in before.vessels}
    decided = {r["id"] for r in before.reviews}
    out: list[dict] = []

    def change(vid: str, kind: str, old: Any, new: Any, review: str | None = None) -> None:
        out.append({"op": "change.record", "vessel_id": vid, "kind": kind, "before_json": old, "after_json": new,
                    "detected_at": now, **({"review_id": review} if review else {})})

    def missed(vessel) -> int:  # earlier complete runs that did not list it
        last = ops.iso(vessel["last_seen_at"], "last_seen_at")
        return sum(at > last for at in history)

    def gone(vessel, runs: int) -> bool:
        return runs >= vanished_runs and _days(now, vessel["last_seen_at"]) >= vanished_days

    upserts = [op for op in sent if op["op"] == "vessel.upsert"]
    listed = {op["id"] for op in upserts} | {
        p["vessel_id"] for op in sent if op["op"] == "review.open" and op["kind"] == "merge"
        for p in (op.get("proposal_json") or {}).get("vessels", ())}
    for op in upserts:
        old = stored.get(op["id"])
        if old is None:
            change(op["id"], "new", None, {"name": op["name"], "slug": op["slug"]})
            continue
        if missed(old) and (old.get("status") == "inactive" or (old.get("status") == "active" and gone(old, missed(old)))):
            change(op["id"], "returned", {"status": old.get("status"), "last_seen_at": old["last_seen_at"]},
                   {"listed_at": now})
        for col, kind in WATCHED:
            if col in op and op[col] != old.get(col) and (old.get(col) is not None or kind == "mmsi"):
                change(op["id"], kind, {col: old.get(col)}, {col: op[col]})
        moved = [c for c in ("port_id", "landing_id") if c in op and old.get(c) is not None and op[c] != old[c]]
        if moved:
            change(op["id"], "moved", {c: old[c] for c in moved}, {c: op[c] for c in moved})

    offered = {o["id"]: (v["id"], o) for v in before.vessels for o in v.get("offerings") or ()}
    offers = [op for op in sent if op["op"] == "offering.upsert"]
    for op in offers:
        vid, ident = op["vessel_id"], op["id"]
        if vid not in stored:
            continue  # a new vessel's offerings are part of "new"
        old = offered.get(ident, (vid, None))[1]
        if old is None or old.get("status") == "retired":
            change(vid, "schedule", None, {"offering_id": ident, "added": op["name"]})
            continue
        if None not in (old.get("price_cents"), op.get("price_cents")) and old["price_cents"] != op["price_cents"]:
            change(vid, "price", {"offering_id": ident, "price_cents": old["price_cents"]},
                   {"offering_id": ident, "price_cents": op["price_cents"]})
        if (old.get("departs_local"), old.get("days") or None) != (op.get("departs_local"), op.get("days_json") or None):
            change(vid, "schedule", {"offering_id": ident, "departs_local": old.get("departs_local"), "days": old.get("days")},
                   {"offering_id": ident, "departs_local": op.get("departs_local"), "days": op.get("days_json")})
    sent_ids, with_offers = {op["id"] for op in offers}, {op["vessel_id"] for op in offers}
    for ident, (vid, old) in sorted(offered.items()):
        if complete and vid in with_offers and old.get("status") == "active" and ident not in sent_ids:
            out.append({"op": "offering.upsert", "id": ident, "vessel_id": vid, "name": old["name"],
                        "trip_type": old["trip_type"], "seen_at": now, "status": "retired"})
            change(vid, "schedule", {"offering_id": ident, "status": "active"}, {"offering_id": ident, "retired": old["name"]})

    if complete:
        for vessel in before.vessels:
            if vessel["id"] in listed or vessel.get("status") != "active" or not gone(vessel, missed(vessel) + 1):
                continue
            last = ops.iso(vessel["last_seen_at"], "last_seen_at")
            print_ = f"{vessel['id']}|{last}"
            review = ops.review_id("vanished", print_)
            if review not in decided:
                out.append({"op": "review.open", "kind": "vanished", "fingerprint": print_, "subject_id": vessel["id"],
                            "candidate_json": {"last_seen_at": last},
                            "proposal_json": {"vessel_id": vessel["id"], "status": "inactive"}, "score": None,
                            "opened_at": now})
            change(vessel["id"], "vanished", {"status": "active"}, {"last_seen_at": last}, review)
    return out


def refresh(ctx: RunContext, sink) -> dict:
    path = ctx.run_dir / "ingest-snapshot.json"
    if not path.exists():
        return {"changes": 0, "no_ingest": 1}
    saved = json.loads(path.read_text(encoding="utf-8"))
    sent = _jsonl(ctx.run_dir / "ingest-ops.jsonl")
    discovered = ctx.run_dir / "discover.json"
    complete = discovered.exists() and json.loads(discovered.read_text(encoding="utf-8")).get("complete") is True
    rules = ctx.region.thresholds["refresh"]
    out = detect(snapshot_from_dict(saved["snapshot"]), sent, saved["now"], complete=complete,
                 history=discovery_history(ctx.run_dir.parent.parent, ctx.run_dir.name), vanished_runs=int(rules["vanished_after_runs"]),
                 vanished_days=float(rules["vanished_after_days"]))
    result = sink.apply(out) if out else {"changed": 0}
    kinds: dict[str, int] = {}
    for op in [*sent, *out]:
        if op["op"] == "change.record":
            kinds[op["kind"]] = kinds.get(op["kind"], 0) + 1
    return {"changes": sum(kinds.values()), "changed": result["changed"], "kinds": dict(sorted(kinds.items())),
            "vanished_reviews": sum(op["op"] == "review.open" for op in out), "complete": int(complete)}

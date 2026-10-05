"""The ``plan-agent`` step: batch manifests for the OSINT agent (design section 8, CF-20).

``python -m skippercast.fleet plan-agent --region CA [--mode full|refresh] [--run-id ID]``

**Selection.** From the registry snapshot (the sink's: the staging database or
the Worker's ``GET /api/fleet/jobs/snapshot``), only ``active`` vessels with no
removal request (when the snapshot carries ``removal_requested_at``) are
considered. A vessel is selected when it is

- ``new``: never profiled (``last_profiled_at`` is null);
- ``stale``: profiled more than the region's ``thresholds.refresh.osint_stale_days`` ago; or
- ``missing`` one of ``website``, ``mmsi``, ``vessel_class``, ``passengers_max``
  or ``trip_types`` (no active offering). ``--mode full`` (the default) selects
  on all three; ``--mode refresh`` only on ``new`` and ``stale``, so a boat
  profiled last week whose MMSI simply is not published is not re-run each week.

Order: new, then stale (oldest profile first), then missing-only; ties by
vessel id. Batches hold at most 20 boats (``BATCH_SIZE``).

**Manifests** are written to ``<run_dir>/manifests/batch-NNN.json`` (numbered
from 001; a re-run of the step in the same run rewrites them and removes stale
ones) and ``agent-plan.json`` holds the counts. A manifest holds only data the
pipeline already has: each boat's id, name, aliases, port and landing ids, the
stored class as a hint, the stored ``known`` keys, what is ``missing`` and, for
a boat profiled before, when and which volatile fields to re-check
(``refresh``). The agent writes one profile per boat, ``<vessel_id>.json``, to
``output_dir`` (``<run_dir>/profiles``); ``ingest --profiles`` reads them. Run
directories live under ``$SKIPPERCAST_FLEET_VAR`` and never enter git (D13).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from . import ops
from .ingest import load_snapshot

__all__ = ["BATCH_SIZE", "KNOWN", "MANIFEST_VERSION", "MODES", "REFRESH_FOCUS", "TARGET_FIELDS", "manifests",
           "plan_agent", "select"]

MANIFEST_VERSION = 1
BATCH_SIZE = 20
MODES = ("full", "refresh")
TARGET_FIELDS = ("website", "mmsi", "vessel_class", "passengers_max", "trip_types")
KNOWN = ("website", "mmsi", "call_sign", "uscg_doc")
REFRESH_FOCUS = ("booking_url", "trip_types")  # what changes between profiles; deterministic sources cover the rest
SCHEMA = "schemas/fleet-profile.schema.json"
VALIDATE = "python -m skippercast.fleet validate-profile <file>"
POLICY = {"off_limits": "catalog/fleet/off-limits.json", "min_interval_s": 1.0, "max_requests_per_boat": 12}


def _time(text: Any) -> datetime:
    return datetime.strptime(ops.iso(text, "time")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _missing(vessel: Mapping[str, Any]) -> list[str]:
    out = [f for f in TARGET_FIELDS[:-1] if vessel.get(f) in (None, "")]
    if not any(o.get("status") == "active" for o in vessel.get("offerings") or ()):
        out.append("trip_types")
    return out


def select(vessels, now: str, stale_days: int, mode: str = "full") -> list[tuple[dict, list[str]]]:
    """(vessel, reasons) for every vessel the agent should profile, in manifest order."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    cutoff = _time(now) - timedelta(days=stale_days)
    chosen = []
    for vessel in vessels:
        if vessel.get("status") != "active" or vessel.get("removal_requested_at"):
            continue
        profiled = vessel.get("last_profiled_at")
        reasons = ["new"] if not profiled else ["stale"] if _time(profiled) < cutoff else []
        if mode == "full" and _missing(vessel):
            reasons.append("missing")
        if reasons:
            rank = 0 if reasons[0] == "new" else 1 if reasons[0] == "stale" else 2
            chosen.append(((rank, ops.iso(profiled, "p") if rank == 1 else "", vessel["id"]), vessel, reasons))
    return [(vessel, reasons) for _key, vessel, reasons in sorted(chosen, key=lambda c: c[0])]


def _boat(vessel: Mapping[str, Any]) -> dict:
    """A manifest entry: snapshot values only."""
    boat = {"vessel_id": vessel["id"], "name": vessel["name"],
            "aliases": sorted({a["alias"] for a in vessel.get("aliases") or () if a.get("alias")}),
            "port": vessel.get("port_id"), "landing": vessel.get("landing_id"),
            "vessel_class_hint": vessel.get("vessel_class"),
            "known": {k: vessel[k] for k in KNOWN if vessel.get(k) not in (None, "")},
            "missing": _missing(vessel)}
    if vessel.get("last_profiled_at"):
        boat["refresh"] = {"last_profiled_at": vessel["last_profiled_at"], "focus": list(REFRESH_FOCUS)}
    return boat


def manifests(region: str, run_id: str, run_dir: Path, created_at: str, chosen, batch_size: int = BATCH_SIZE) -> list[dict]:
    """The batch manifests for ``chosen`` (``select``'s output), at most ``batch_size`` (<= 20) boats each."""
    if not 1 <= batch_size <= BATCH_SIZE:
        raise ValueError(f"batch_size must be 1-{BATCH_SIZE}")
    run_dir = Path(run_dir)
    var = run_dir.parents[2]  # <FLEET_VAR>/<region>/runs/<run_id>
    out = []
    for start in range(0, len(chosen), batch_size):
        out.append({
            "manifest_version": MANIFEST_VERSION, "region": region, "run_id": run_id,
            "batch_id": f"batch-{start // batch_size + 1:03d}", "created_at": ops.iso(created_at, "created_at")[:19] + "Z",
            "output_dir": str(run_dir / "profiles"), "output_file": "<vessel_id>.json",
            "schema": SCHEMA, "validate": VALIDATE,
            "policy": {**POLICY, "cache_dir": str(var / region / "http-cache" / "agent")},
            "boats": [_boat(vessel) for vessel, _reasons in chosen[start:start + batch_size]],
        })
    return out


def plan_agent(ctx, sink, mode: str = "full", load=load_snapshot, batch_size: int = BATCH_SIZE) -> dict:
    """Write this run's manifests and ``agent-plan.json``; counts for ``state.json``."""
    snapshot = load(sink, ctx.region.id)
    now = ctx.clock()
    stale_days = int(ctx.region.thresholds["refresh"]["osint_stale_days"])
    chosen = select(snapshot.vessels, now, stale_days, mode)
    docs = manifests(ctx.region.id, ctx.run_dir.name, ctx.run_dir, now, chosen, batch_size)
    folder = ctx.run_dir / "manifests"
    folder.mkdir(exist_ok=True)
    (ctx.run_dir / "profiles").mkdir(exist_ok=True)
    names = {f"{doc['batch_id']}.json" for doc in docs}
    for old in folder.glob("batch-*.json"):
        if old.name not in names:
            old.unlink()
    for doc in docs:
        (folder / f"{doc['batch_id']}.json").write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                                        encoding="utf-8")
    reasons = {r: sum(r in rs for _v, rs in chosen) for r in ("new", "stale", "missing")}
    counts = {"vessels": len(snapshot.vessels), "selected": len(chosen), "batches": len(docs), **reasons}
    plan = {"at": ops.iso(now, "at"), "mode": mode, "stale_days": stale_days, "batch_size": batch_size, "counts": counts,
            "batches": sorted(names)}
    (ctx.run_dir / "agent-plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return counts

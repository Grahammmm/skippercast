"""``coverage-status``: the ``charter-identity`` coverage the registry gives each coastal region.

``python -m skippercast.fleet coverage-status --region CA [--sink staging|worker] [--apply]``

The fleet registry (catalog source ``fleet-registry``) supersedes
``operator-identities`` as the charter identity register (design section 6,
"Relationship to the existing reports pipeline"). For every coastal region a
fleet port maps to (``fleet.json`` ``ports[].region``) this counts the
registry's active vessels whose resolved port is one of those ports, and those
with an MMSI, and derives the status: ``missing`` with none, else ``partial``.
It never says ``ready``: an MMSI in the registry is not an operator-confirmed
identity (``catalog/data-needs.json`` ``charter-identity``). The reason holds
counts only, never names, contacts or URLs.

``--apply`` writes the status into each mapped ``regions/<id>/region.json``
``coverage.charter-identity`` (that entry only, formatting kept); then rebuild
with ``PYTHONPATH=src python -m skippercast.platform.build``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Mapping

from ..paths import repo_root
from .config import FleetRegion, load_region
from .ingest import load_snapshot
from .resolve import Snapshot
from .runs import fleet_var, new_run_id
from .sinks import SqliteSink, WorkerSink, worker_base

NEED, SOURCE = "charter-identity", "fleet-registry"
# The coverage of a coastal region no fleet port maps to (set once; coverage-status only writes mapped regions).
UNMAPPED = {"status": "missing", "reason": "0 charter fleet ports map to this region; the charter fleet registry counts no boats here."}
ENTRY = re.compile(r'(\n    "charter-identity": \{\n      "status": )"[^"]*"(,\n      "reason": )"(?:[^"\\]|\\.)*"(\n    \})')


def reason(boats: int, mmsi: int) -> str:
    return (f"{boats} {'boat' if boats == 1 else 'boats'} registered in the charter fleet registry, {mmsi} with an "
            "identified MMSI; registry identities are not operator-confirmed.")


def coverage_status(region: FleetRegion, snapshot: Snapshot) -> dict[str, dict]:
    """``{coastal region id: {"status", "reason"}}`` for every coastal region the fleet region's ports map to."""
    coastal = {p.id: p.region for p in region.ports if p.region}
    counts = {ident: [0, 0] for ident in sorted(set(coastal.values()))}
    for vessel in snapshot.vessels:
        ident = coastal.get(vessel.get("port_id"))
        if ident and vessel.get("status") == "active":
            counts[ident][0] += 1
            counts[ident][1] += bool(vessel.get("mmsi"))
    return {ident: {"status": "partial" if boats else "missing", "reason": reason(boats, mmsi)}
            for ident, (boats, mmsi) in counts.items()}


def apply(statuses: Mapping[str, Mapping[str, str]], root: Path | None = None) -> list[str]:
    """Write each status into its region.json; the regions whose file changed."""
    changed = []
    for ident, status in sorted(statuses.items()):
        path = Path(root or repo_root()) / "regions" / ident / "region.json"
        text = path.read_text(encoding="utf-8")
        if SOURCE not in json.loads(text)["source_bindings"].get(NEED, []):
            raise ValueError(f"{ident}: {NEED} is not bound to {SOURCE}")
        new, count = ENTRY.subn(lambda m: m[1] + json.dumps(status["status"]) + m[2] + json.dumps(status["reason"]) + m[3],
                                text)
        if count != 1 or json.loads(new)["coverage"][NEED] != dict(status):
            raise ValueError(f"{ident}: no single coverage.{NEED} entry to update")
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(ident)
    return changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet coverage-status", description=__doc__.splitlines()[0])
    parser.add_argument("--region", required=True, help="fleet region id, e.g. CA")
    parser.add_argument("--sink", choices=["staging", "worker"], default="staging", help="the registry to count")
    parser.add_argument("--apply", action="store_true", help="write the statuses into regions/*/region.json")
    args = parser.parse_args(argv)
    region = load_region(args.region)
    run_id = new_run_id()
    if args.sink == "staging":
        path = fleet_var() / "staging" / f"{region.id}.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        sink = SqliteSink(path, region.id, run_id)
    else:
        sink = WorkerSink(worker_base(), region.id, run_id, lambda: 0)
    try:
        statuses = coverage_status(region, load_snapshot(sink, region.id))
    finally:
        sink.close()
    print(json.dumps(statuses, indent=2, sort_keys=True))
    if args.apply:
        print("updated: " + (", ".join(apply(statuses)) or "nothing"), file=sys.stderr)
    return 0

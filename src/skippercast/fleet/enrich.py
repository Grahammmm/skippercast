"""The ``enrich-code`` step (design sections 4 and 6): deterministic enrichment after resolve.

``python -m skippercast.fleet enrich-code --region CA [--run-id ID]``

1. **Vessels** come from the run's ``resolved.jsonl`` (CF-15): one object per
   vessel with ``vessel_id`` (or ``id``), ``name``, ``port_id``, and when known
   ``website`` and ``place_id``.
2. **Enrich adapters** of the region's enabled bindings run over every vessel:
   ``operator-site`` (contact facts from the operator's own site) and
   ``google-places`` (``place_id``; skipped and reported without
   ``GOOGLE_PLACES_API_KEY``). Their facts go to ``facts.jsonl``, one row per
   fact with its ``vessel_id``; a fact with ``flags`` (a webmail address) needs a
   review before it may win, which ingest opens.
3. **File imports** (``file-import`` bindings, e.g. the CPRA CPFV list) read
   their owner-supplied file and write candidates to ``imported.jsonl`` for the
   next resolve.
4. **Retention**: when the region binds ``google-places``, the step sends
   ``places_purge_ops`` to the sink, deleting stored Places content the terms do
   not allow to be kept (everything but ``place_id``; see
   ``adapters/google_places.py``). It runs with or without the key.

The step writes ``enrich-code.json`` (per-binding reports: counts, skip reasons,
no contact values) and returns counts for ``state.json``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .adapters import RunContext
from .adapters.file_import import FileImport, FileImportError
from .adapters.google_places import GooglePlaces, places_purge_ops
from .adapters.operator_site import OperatorSite

ENRICHERS = {"operator-site": OperatorSite, "google-places": GooglePlaces}
IMPORTERS = {"file-import": FileImport}


def load_vessels(run_dir: Path) -> list[dict]:
    """The resolved vessels of this run (``resolved.jsonl``), each with a ``vessel_id``."""
    path = Path(run_dir) / "resolved.jsonl"
    if not path.exists():
        return []
    vessels = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        ident = row.get("vessel_id") or row.get("id")
        if isinstance(ident, str) and ident:
            vessels.append({**row, "vessel_id": ident})
    return vessels


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            count += 1
    return count


def enrich_code(ctx: RunContext, sink, vessels: list[Mapping[str, Any]] | None = None,
                adapters: Mapping[str, Any] | None = None) -> dict:
    """Run the step; ``adapters`` maps an adapter id to a ready instance (tests pass fakes)."""
    vessels = load_vessels(ctx.run_dir) if vessels is None else [dict(v) for v in vessels]
    adapters = dict(adapters or {})
    report: dict[str, Any] = {"vessels": len(vessels), "bindings": {}}
    facts: list[dict] = []
    imported: list[dict] = []

    for binding in ctx.region.enabled_sources():
        if binding.adapter in ENRICHERS:
            adapter = adapters.get(binding.adapter) or ENRICHERS[binding.adapter]()
            if hasattr(adapter, "prepare"):
                adapter.prepare(vessels, binding, ctx)
            for vessel in vessels:
                for fact in adapter.enrich(vessel, binding, ctx):
                    facts.append({"vessel_id": vessel["vessel_id"], **fact.as_dict()})
            report["bindings"][binding.id] = getattr(adapter, "report", {})
        elif binding.adapter in IMPORTERS:
            adapter = adapters.get(binding.adapter) or IMPORTERS[binding.adapter]()
            try:
                imported += [c.as_dict() for c in adapter.discover(binding, ctx)]
                report["bindings"][binding.id] = adapter.report.get(binding.id, {})
            except FileImportError as error:
                report["bindings"][binding.id] = {"status": "failed", "error": str(error)}

    purged = 0
    if any(b.adapter == "google-places" for b in ctx.region.sources):
        result = sink.apply(places_purge_ops(ctx.clock()))
        purged = result.get("changed", 0)
    report["purged_places_facts"] = purged

    counts = {
        "vessels": len(vessels),
        "facts": _write_jsonl(ctx.run_dir / "facts.jsonl", facts),
        "flagged": sum(1 for f in facts if f.get("flags")),
        "imported": _write_jsonl(ctx.run_dir / "imported.jsonl", imported),
        "purged": purged,
        "places_skipped": int(any(isinstance(r, Mapping) and r.get("status") == "skipped"
                                  for b, r in report["bindings"].items()
                                  if ctx.region.binding(b).adapter == "google-places")),
    }
    report["counts"] = counts
    (ctx.run_dir / "enrich-code.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return counts


def step(ctx: RunContext, sink) -> dict:
    return enrich_code(ctx, sink)

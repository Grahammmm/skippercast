"""enrich_code keeps each binding's report as it was when that binding completed.

Synthetic ready adapters only: no network, sink, source file or real adapter constructor.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from skippercast.fleet import enrich
from skippercast.fleet.adapters import RunContext
from skippercast.fleet.adapters.file_import import FileImportError

NOW = "2026-10-05T10:00:00Z"
VESSEL = {"vessel_id": "v-1", "name": "Synthetic"}


def _binding(ident, adapter):
    return SimpleNamespace(id=ident, adapter=adapter, enabled=True, rights="public-record", params={})


class _Item:
    def __init__(self, row):
        self.row = row

    def as_dict(self):
        return dict(self.row)


class _SharedReportEnricher:
    """One persistent report object, mutated in place (never replaced) for each binding."""

    def __init__(self):
        self.calls = []
        self.report = {"status": "none", "stats": {"binding": None, "samples": []}}

    def prepare(self, vessels, binding, ctx):
        self.calls.append(("prepare", binding.id))
        self.report["status"] = "ok-" + binding.id
        self.report["stats"]["binding"] = binding.id
        self.report["stats"]["samples"].append(len(self.report["stats"]["samples"]) + 1)

    def enrich(self, vessel, binding, ctx):
        self.calls.append(("enrich", binding.id))
        return []


class _SharedNestedImporter:
    """Distinct outer per-binding records that share one mutable nested stats dict."""

    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)
        self.stats = {"binding": None, "samples": []}
        self.report = {}

    def discover(self, binding, ctx):
        self.calls.append(binding.id)
        if binding.id in self.fail:
            raise FileImportError("synthetic failure")
        self.stats["binding"] = binding.id
        self.stats["samples"].append(len(self.calls))
        self.report[binding.id] = {"status": "ok", "stats": self.stats}
        return [_Item({"name": "cand-" + binding.id})]


class ReportSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_step(self, specs, adapters, vessels=(VESSEL,)):
        sources = tuple(_binding(i, a) for i, a in specs)
        region = SimpleNamespace(sources=sources, enabled_sources=lambda: sources,
                                 binding=lambda ident: next(b for b in sources if b.id == ident))
        ctx = RunContext(region=region, net=None, run_dir=self.tmp, clock=lambda: NOW)
        counts = enrich.enrich_code(ctx, None, vessels=list(vessels), adapters=adapters)
        return counts, json.loads((self.tmp / "enrich-code.json").read_text())

    def test_reused_enricher_keeps_each_completed_report(self):
        adapter = _SharedReportEnricher()
        counts, out = self.run_step([("synthetic-first", "operator-site"), ("synthetic-second", "operator-site")],
                                    {"operator-site": adapter})
        self.assertEqual(out["bindings"]["synthetic-first"]["status"], "ok-synthetic-first")
        self.assertEqual(out["bindings"]["synthetic-second"]["status"], "ok-synthetic-second")
        self.assertEqual(adapter.calls, [("prepare", "synthetic-first"), ("enrich", "synthetic-first"),
                                         ("prepare", "synthetic-second"), ("enrich", "synthetic-second")])
        self.assertEqual(counts, {"vessels": 1, "facts": 0, "flagged": 0, "imported": 0, "purged": 0,
                                  "places_skipped": 0})

    def test_nested_report_mutation_requires_deep_snapshot(self):
        _, out = self.run_step([("synthetic-first", "operator-site"), ("synthetic-second", "operator-site")],
                               {"operator-site": _SharedReportEnricher()})
        self.assertEqual(out["bindings"]["synthetic-first"]["stats"],
                         {"binding": "synthetic-first", "samples": [1]})
        self.assertEqual(out["bindings"]["synthetic-second"]["stats"],
                         {"binding": "synthetic-second", "samples": [1, 2]})

    def test_reused_importer_snapshots_selected_binding_record(self):
        adapter = _SharedNestedImporter()
        counts, out = self.run_step([("synthetic-import-first", "file-import"),
                                     ("synthetic-import-second", "file-import")], {"file-import": adapter})
        self.assertEqual(out["bindings"]["synthetic-import-first"],
                         {"status": "ok", "stats": {"binding": "synthetic-import-first", "samples": [1]}})
        self.assertEqual(out["bindings"]["synthetic-import-second"],
                         {"status": "ok", "stats": {"binding": "synthetic-import-second", "samples": [1, 2]}})
        self.assertEqual(adapter.calls, ["synthetic-import-first", "synthetic-import-second"])
        self.assertEqual(counts["imported"], 2)

    def test_later_binding_mutation_cannot_change_prior_status(self):
        adapter = _SharedNestedImporter()
        original = adapter.discover

        def discover(binding, ctx):
            result = original(binding, ctx)
            adapter.report[binding.id]["status"] = "done-" + binding.id
            if binding.id != "synthetic-import-first":
                adapter.report["synthetic-import-first"]["status"] = "rewritten-later"
            return result

        adapter.discover = discover
        _, out = self.run_step([("synthetic-import-first", "file-import"),
                                ("synthetic-import-second", "file-import")], {"file-import": adapter})
        self.assertEqual(out["bindings"]["synthetic-import-first"]["status"], "done-synthetic-import-first")
        self.assertEqual(out["bindings"]["synthetic-import-second"]["status"], "done-synthetic-import-second")

    def test_fallback_and_failure_reporting_unchanged(self):
        class NoReport:
            def enrich(self, vessel, binding, ctx):
                return []

        class NoKey:
            report = {"other": {"status": "ok"}}

            def discover(self, binding, ctx):
                return []

        _, out = self.run_step([("e", "operator-site"), ("i", "file-import")],
                               {"operator-site": NoReport(), "file-import": NoKey()})
        self.assertEqual(out["bindings"], {"e": {}, "i": {}})
        _, out = self.run_step([("bad", "file-import"), ("good", "file-import")],
                               {"file-import": _SharedNestedImporter(fail={"bad"})})
        self.assertEqual(out["bindings"]["bad"], {"status": "failed", "error": "synthetic failure"})
        self.assertEqual(out["bindings"]["good"]["status"], "ok")

    def test_ordinary_outputs_and_empty_run_remain_exact(self):
        class Plain:
            report = {"status": "ok", "n": 1}

            def enrich(self, vessel, binding, ctx):
                return [_Item({"field": "phone", "value": "x", "flags": ["webmail"]})]

        counts, out = self.run_step([("site", "operator-site")], {"operator-site": Plain()})
        self.assertEqual(counts["facts"], 1)
        self.assertEqual(counts["flagged"], 1)
        self.assertEqual(out["bindings"], {"site": {"status": "ok", "n": 1}})
        row = json.loads((self.tmp / "facts.jsonl").read_text())
        self.assertEqual(row, {"vessel_id": "v-1", "field": "phone", "value": "x", "flags": ["webmail"]})
        counts, out = self.run_step([], {}, vessels=())
        self.assertEqual(counts, {"vessels": 0, "facts": 0, "flagged": 0, "imported": 0, "purged": 0,
                                  "places_skipped": 0})
        self.assertEqual(out["bindings"], {})
        self.assertEqual((self.tmp / "enrich-code.json").read_text()[-2:], "}\n")


if __name__ == "__main__":
    unittest.main()

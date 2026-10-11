"""Offline scout CSV regression: invented public businesses and boats only."""
import csv
import io
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from skippercast.fleet import enrich, ingest, ops
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.file_import import FileImport, FileImportError, read_rows
from skippercast.fleet.config import load_region
from skippercast.fleet.resolve import ResolverConfig, Snapshot, resolve
from skippercast.fleet.runs import Run

NOW = "2026-10-11T00:00:00Z"
HEADERS = "port_id,boat,operator,class,landing,website,evidence_urls".split(",")


class ScoutImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Run("CA", "20261011T000000Z-abcdef", var=Path(self.tmp.name))
        self.region = load_region("CA")
        self.ctx = RunContext(self.region, None, self.run.dir, lambda: NOW)
        self.binding = self.region.binding("scout-candidates-2026-10-10")
        self.path = Path(self.tmp.name) / "CA" / self.binding.params["path"]

    def write(self, rows):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(HEADERS)
        writer.writerows(rows)
        self.path.write_text(buffer.getvalue())

    def row(self, **kwargs):
        data = dict(zip(HEADERS, ["morro-bay", "Sea Example", "Example Charters", "party", "",
                                "https://sea.example/", "https://sea.example/fleet|https://landing.example/boats"]))
        return [kwargs.get(key, data[key]) for key in HEADERS]

    def test_public_provenance_ports_and_website_resolve(self):
        self.write([self.row()])
        candidate = list(FileImport().discover(self.binding, self.ctx))[0]
        self.assertEqual(candidate.port_hint, "morro-bay")
        self.assertEqual(candidate.keys, {})
        self.assertTrue(all(f.method == "page" and f.rights == "facts-only" for f in candidate.facts))
        self.assertEqual({f.source_url for f in candidate.facts},
                         {"https://sea.example/fleet", "https://landing.example/boats"})
        self.assertFalse(any(f.field.startswith("cdfw.") or f.field == "vessel_class" for f in candidate.facts))
        config = ResolverConfig.from_region(self.region)
        result = resolve(Snapshot([], [], [], frozenset(), []), [candidate], config, NOW)
        vessel = next(op for op in result.ops if op["op"] == "vessel.upsert")
        self.assertEqual(vessel["website"], "https://sea.example/")
        self.assertEqual(vessel["port_id"], "morro-bay")
        self.assertTrue(any(op["op"] == "operator.upsert" for op in result.ops))
        for op in result.ops:
            ops.validate_op(op, 0, "CA")
        self.assertEqual(result.skipped, [])

    def test_seed_discovered_before_resolve_and_operator_site_enrichment(self):
        self.write([self.row()])
        region = replace(self.region, sources=(self.binding, self.region.binding("operator-site")))
        ctx = RunContext(region, None, self.run.dir, lambda: NOW)
        counts = ingest.discover(ctx, None)
        self.assertEqual(counts["candidates"], 1)
        report = json.loads((self.run.dir / "discover.json").read_text())
        self.assertEqual(report["bindings"][self.binding.id]["rows"], 1)
        ingest.resolve_step(ctx, None, load=lambda *_: Snapshot([], [], [], frozenset(), []))
        resolved = json.loads((self.run.dir / "resolved.jsonl").read_text())
        self.assertEqual(resolved["website"], "https://sea.example/")
        seen = []

        class RecordingSite:
            def enrich(self, vessel, binding, ctx):
                seen.append((vessel["vessel_id"], vessel["website"]))
                return []

        enrich.enrich_code(ctx, None, adapters={"operator-site": RecordingSite()})
        self.assertEqual(seen, [(resolved["vessel_id"], "https://sea.example/")])

    def test_blocked_sources_http_and_person_names_never_emitted(self):
        self.write([self.row(operator="Pat Placeholder", website="https://sub.facebook.com/test",
                             evidence_urls="https://fishingbooker.com/test|http://sea.example/page|https://sea.example/fleet"),
                    self.row(boat="Pretend Boat", operator="Pat Placeholder DBA Example Charters LLC",
                             website="", evidence_urls="https://sea.example/boats")])
        adapter = FileImport()
        candidates = list(adapter.discover(self.binding, self.ctx))
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(not self.region.is_off_limits(f.source_url) for c in candidates for f in c.facts))
        self.assertFalse(any(f.field in ("operator", "website") for c in candidates for f in c.facts))
        self.assertNotIn("Pat Placeholder", str(candidates))
        self.assertEqual(adapter.report[self.binding.id]["operator_names_dropped"], 2)
        self.assertEqual(adapter.report[self.binding.id]["urls_dropped"], 3)

    def test_missing_evidence_website_fallback_and_invalid_port_counted(self):
        self.write([self.row(evidence_urls=""), self.row(boat="Pretend Boat", website="", evidence_urls=""),
                    self.row(boat="Another Example", port_id="foreign-port")])
        adapter = FileImport()
        candidates = list(adapter.discover(self.binding, self.ctx))
        self.assertEqual(len(candidates), 1)
        self.assertEqual({f.source_url for f in candidates[0].facts}, {"https://sea.example/"})
        report = adapter.report[self.binding.id]
        self.assertEqual((report["rows"], report["rows_without_evidence"], report["rows_without_port"]), (3, 1, 1))

    def test_stable_record_identity_and_multiple_evidence(self):
        self.write([self.row(), self.row(port_id="san-diego")])
        first = list(FileImport().discover(self.binding, self.ctx))
        self.write([self.row(evidence_urls="https://other.example/page"), self.row(port_id="san-diego")])
        second = list(FileImport().discover(self.binding, self.ctx))
        self.assertEqual(first[0].record_id, second[0].record_id)
        self.assertNotEqual(first[0].record_id, first[1].record_id)

    def test_all_headers_required_and_no_network(self):
        with self.assertRaises(FileImportError):
            read_rows(b"port_id,boat\nmorro-bay,Sea Example\n", "scout-candidates-v1")
        self.write([self.row()])
        self.assertEqual(len(list(FileImport().discover(self.binding, self.ctx))), 1)
        self.assertIsNone(self.ctx.net)

    def test_existing_sources_rank_ahead_of_scout_website(self):
        priority = self.region.resolver["website"].priority
        self.assertLess(priority.index("operator-site"), priority.index("file-import"))
        self.assertLess(priority.index("landing-pages"), priority.index("file-import"))

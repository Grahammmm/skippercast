"""``coverage-status`` and the fleet-registry binding (design section 6 "Relationship to the existing reports
pipeline", CF-17). The registry rows are synthetic; only counts may reach a region's coverage reason."""
import json
from datetime import date
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from skippercast.fleet import confirm, coverage
from skippercast.fleet.resolve import Snapshot
from tests._support import ROOT
from tests.unit.test_fleet_ingest import BASE, Pipeline, baseline, day

LEGACY = re.compile(r"^\d+ boats? registered in the charter fleet registry, \d+ with an identified MMSI; "
                    r"registry identities are not operator-confirmed\.$")
REASON = re.compile(r"^\d+ boats? registered in the charter fleet registry, \d+ with an identified MMSI; "
                    r"\d+ operator-confirmed identities; ready threshold is an owner decision\.$")


def regions():
    return {p.parent.name: json.loads(p.read_text()) for p in sorted((ROOT / "regions").glob("*/region.json"))}


def vessel(n, port, mmsi=None, status="active"):
    return {"id": f"{n:032x}", "port_id": port, "mmsi": mmsi, "status": status, "name": f"Test Boat {n}"}


class CoverageStatusTests(unittest.TestCase):
    def test_status_per_mapped_coastal_region_with_counts_only(self):
        snapshot = Snapshot([vessel(1, "morro-bay", "999000001"), vessel(2, "port-san-luis"), vessel(3, "morro-bay"),
                             vessel(4, "morro-bay", "999000004", status="excluded"), vessel(5, "san-francisco"),
                             vessel(6, "monterey", "999000006")])
        result = coverage.coverage_status(BASE, snapshot)
        mapped = {p.region for p in BASE.ports if p.region}
        self.assertEqual(set(result), mapped)
        self.assertEqual(result["morro-bay"], {"status": "partial", "reason": coverage.reason(3, 1, 0)})
        self.assertEqual(result["monterey-point-sur"]["status"], "partial")
        self.assertEqual(result["crescent-city"], {"status": "missing", "reason": coverage.reason(0, 0, 0)})
        self.assertNotIn("ready", {r["status"] for r in result.values()})
        for item in result.values():
            self.assertRegex(item["reason"], REASON)
            self.assertNotRegex(item["reason"], r"Test Boat|https?:|\+1|@|999\d{6}")

    def test_counts_come_from_a_staging_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline(tmp)
            p.run(day(0), *baseline(day(0)))
            db = p.db()
            db.execute("UPDATE fleet_vessels SET mmsi='999000001' WHERE name='Sea Example'")
            result = coverage.coverage_status(BASE, Snapshot.from_sqlite(db, "CA"))
            db.close()
        self.assertEqual(result["morro-bay"]["reason"], coverage.reason(5, 1, 0))

    def test_no_region_binds_charter_identity_to_a_superseded_source(self):
        sources = {s["id"]: s for s in json.loads((ROOT / "catalog/sources.json").read_text())["sources"]}
        self.assertEqual(sources["operator-identities"]["superseded_by"], "fleet-registry")
        self.assertEqual(sources["fleet-registry"]["review_status"], "approved")
        superseded = {i for i, s in sources.items() if s.get("superseded_by")}
        for ident, region in regions().items():
            with self.subTest(region=ident):
                self.assertEqual(region["source_bindings"]["charter-identity"], ["fleet-registry"])
                for bound in region["source_bindings"].values():
                    self.assertFalse(superseded & set(bound))

    def test_committed_coverage_is_counts_only(self):
        mapped = {p.region for p in BASE.ports if p.region}
        for ident, region in regions().items():
            with self.subTest(region=ident):
                entry = region["coverage"]["charter-identity"]
                if ident in mapped:
                    self.assertIn(entry["status"], {"missing", "partial"})
                    self.assertRegex(entry["reason"], LEGACY)
                else:
                    self.assertEqual(entry, coverage.UNMAPPED)

    def test_apply_rewrites_only_the_coverage_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "regions/morro-bay", root / "regions/morro-bay")
            before = (root / "regions/morro-bay/region.json").read_text()
            status = {"status": "partial", "reason": coverage.reason(12, 3)}
            self.assertEqual(coverage.apply({"morro-bay": status}, root), ["morro-bay"])
            after = (root / "regions/morro-bay/region.json").read_text()
            self.assertEqual(json.loads(after)["coverage"]["charter-identity"], status)
            changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
            self.assertEqual(len(changed), 2, "status and reason lines only")
            self.assertEqual(len(before.splitlines()), len(after.splitlines()))
            self.assertEqual(coverage.apply({"morro-bay": status}, root), [])

    def test_coverage_confirmed_counts_never_ready(self):
        snapshot = Snapshot([vessel(1, "morro-bay", "999000001"), vessel(2, "port-san-luis", "999000002"),
                             vessel(3, "morro-bay"), vessel(4, "morro-bay", "999000004", status="excluded"),
                             vessel(5, "san-francisco", "999000005"), vessel(6, "monterey", "999000006")])
        v = {n: vessel(n, "x")["id"] for n in range(1, 7)}

        def entry(n, mmsi, withdrawn=None):
            return {"vessel_id": v[n], "mmsi": mmsi, "method": "operator-statement", "confirmed_on": "2026-11-01",
                    "evidence_ref": "ref-1", "withdrawn_on": withdrawn}

        def counts(entries):
            result = coverage.coverage_status(BASE, snapshot, entries)
            for item in result.values():
                self.assertRegex(item["reason"], REASON)
            self.assertNotIn("ready", {r["status"] for r in result.values()})
            return result["morro-bay"]["reason"], result["monterey-point-sur"]["reason"], result

        self.assertEqual(counts(())[:2], (coverage.reason(3, 2, 0), coverage.reason(1, 1, 0)))
        self.assertEqual(coverage.coverage_status(BASE, snapshot), coverage.coverage_status(BASE, snapshot, ()))
        self.assertEqual(counts([entry(1, "999000001")])[:2], (coverage.reason(3, 2, 1), coverage.reason(1, 1, 0)))
        everyone = [entry(1, "999000001"), entry(2, "999000002"), entry(6, "999000006")]
        morro, monterey, result = counts(everyone)
        self.assertEqual((morro, monterey), (coverage.reason(3, 2, 2), coverage.reason(1, 1, 1)))
        self.assertEqual({r["status"] for r in result.values() if "0 boats" not in r["reason"]}, {"partial"},
                         "all confirmed is still partial: ready is an owner decision")
        self.assertEqual(result["crescent-city"]["status"], "missing")
        for label, entries in (("withdrawn", [entry(1, "999000001", "2026-11-02")]),
                               ("stale: the registry's MMSI moved", [entry(1, "999000099")]),
                               ("excluded vessel", [entry(4, "999000004")]),
                               ("unmapped port", [entry(5, "999000005")]),
                               ("unknown vessel", [{**entry(1, "999000001"), "vessel_id": "f" * 32}]),
                               ("a boat the registry holds no MMSI for", [entry(3, "999000003")])):
            with self.subTest(label):
                self.assertEqual(counts(entries)[:2], (coverage.reason(3, 2, 0), coverage.reason(1, 1, 0)))
        self.assertEqual(counts([entry(1, "999000001"), entry(1, "999000099")])[0], coverage.reason(3, 2, 1),
                         "one vessel counts once")

    def test_confirmations_are_read_per_region_and_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            var = Path(tmp)
            held = lambda: {vessel(1, "x")["id"]: "999000001"}  # noqa: E731
            args = (vessel(1, "x")["id"], "999000001", "operator-statement", "2026-11-01", "ref-1", held)
            self.assertEqual(confirm.add("CA", "staging", *args, var=var, now=date(2026, 11, 4)), 1)
            snapshot = Snapshot([vessel(1, "morro-bay", "999000001")])
            for region, sink, expected in (("CA", "staging", 1), ("CA", "worker", 0), ("WA", "staging", 0)):
                with self.subTest(region=region, sink=sink):
                    entries = confirm.load_confirmations(region, sink, var)
                    self.assertEqual(coverage.coverage_status(BASE, snapshot, entries)["morro-bay"]["reason"],
                                     coverage.reason(1, 1, expected))


if __name__ == "__main__":
    unittest.main()

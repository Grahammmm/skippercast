"""``coverage-status`` and the fleet-registry binding (design section 6 "Relationship to the existing reports
pipeline", CF-17). The registry rows are synthetic; only counts may reach a region's coverage reason."""
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from skippercast.fleet import coverage
from skippercast.fleet.resolve import Snapshot
from tests._support import ROOT
from tests.unit.test_fleet_ingest import BASE, Pipeline, baseline, day

REASON = re.compile(r"^\d+ boats? registered in the charter fleet registry, \d+ with an identified MMSI; "
                    r"registry identities are not operator-confirmed\.$")


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
        self.assertEqual(result["morro-bay"], {"status": "partial", "reason": coverage.reason(3, 1)})
        self.assertEqual(result["monterey-point-sur"]["status"], "partial")
        self.assertEqual(result["crescent-city"], {"status": "missing", "reason": coverage.reason(0, 0)})
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
        self.assertEqual(result["morro-bay"]["reason"], coverage.reason(5, 1))

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
                    self.assertRegex(entry["reason"], REASON)
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


if __name__ == "__main__":
    unittest.main()

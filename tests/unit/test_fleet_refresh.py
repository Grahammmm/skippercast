"""Change detection (design section 9 "Change detection", CF-17) end to end on the SqliteSink.

The synthetic fleet of ``test_fleet_ingest`` runs on day 0, 20 and 40 without
one boat, then on day 50 with one delta of each kind; the CA thresholds
(``vanished_after_runs`` 3, ``vanished_after_days`` 45) are the region's own.
"""
from collections import Counter
import tempfile
import unittest

from skippercast.fleet.refresh import detect
from skippercast.fleet.resolve import Snapshot
from tests.unit.test_fleet_ingest import REGION, Pipeline, baseline, day, landing, psix


def kinds(p, run_id):
    return Counter(c["kind"] for c in p.rows("fleet_changes") if c["run_id"] == run_id)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_thresholds_are_the_regions(self):
        self.assertEqual((REGION.thresholds["refresh"]["vanished_after_runs"],
                          REGION.thresholds["refresh"]["vanished_after_days"]), (3, 45))

    def test_fixture_deltas_give_exactly_one_change_of_each_kind(self):
        for worker in (False, True):
            with self.subTest(worker=worker), tempfile.TemporaryDirectory() as tmp:
                p = Pipeline(tmp, worker)
                first = p.run(day(0), *baseline(day(0)))
                self.assertEqual(kinds(p, first["run_id"]), {"new": 5})
                for n in (20, 40):  # Rockfish Test is no longer listed: not vanished yet (runs, then days)
                    quiet = p.run(day(n), *baseline(day(n), rockfish=False))
                    self.assertEqual(kinds(p, quiet["run_id"]), Counter(), n)
                at = day(50)
                land, registry = baseline(at, rockfish=False)
                land[0] = landing("Sea Example", at, operator="Example Charters LLC",
                                  offerings=[("Half Day", 10500, "06:30")], departures=["2026-11-28"])  # price
                land[1] = landing("Kelp Test", at, operator="Test Fishing Inc",                          # sold
                                  offerings=[("Full Day", 15000, "05:30")])                               # schedule
                land.append(landing("Harbor Light Test", at))                                             # new
                registry[3] = psix("Fog Cutter Test", "1000005", at)                                      # renamed
                delta = p.run(at, land, registry)
                self.assertEqual(kinds(p, delta["run_id"]),
                                 {k: 1 for k in ("new", "renamed", "sold", "vanished", "price", "schedule")})
                self.assertEqual(delta["steps"]["refresh"]["counts"]["kinds"],
                                 {k: 1 for k in ("new", "price", "renamed", "schedule", "sold", "vanished")})
                review = [r for r in p.rows("fleet_reviews") if r["kind"] == "vanished"]
                self.assertEqual((len(review), review[0]["status"]), (1, "open"))
                self.assertEqual(p.vessel("Rockfish Test")["status"], "active", "status changes only on the decision")
                again = p.run(at, land, registry, run_id=delta["run_id"])
                self.assertEqual(again["steps"]["refresh"]["counts"]["changed"], 0, "a rerun records nothing new")

    def test_a_failed_source_never_counts_towards_vanished(self):
        p = Pipeline(self.tmp.name)
        p.run(day(0), *baseline(day(0)))
        p.psix.error = RuntimeError("psix down")
        for n in (20, 40, 60, 80):
            report = p.run(day(n), *baseline(day(n), rockfish=False))
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["steps"]["discover"]["counts"]["failed"], 1)
        self.assertEqual([c["kind"] for c in p.rows("fleet_changes") if c["kind"] == "vanished"], [])
        runs = {r["step"]: r["status"] for r in p.rows("fleet_runs") if r["id"].startswith(report["run_id"])}
        self.assertEqual(runs["discover"], "partial")

    def test_retired_offering_moved_mmsi_and_returned(self):
        old = {"id": "a" * 32, "slug": "sea-example", "name": "Sea Example", "status": "inactive", "port_id": "morro-bay",
               "landing_id": None, "operator_id": None, "mmsi": None, "vessel_class": None,
               "last_seen_at": "2026-08-01T09:47:00.000Z",
               "offerings": [{"id": "b" * 32, "name": "Half Day", "trip_type": "half-day", "status": "active",
                              "price_cents": 9500, "departs_local": "06:30", "days": ["sat"]}]}
        sent = [{"op": "vessel.upsert", "id": "a" * 32, "slug": "sea-example", "name": "Sea Example",
                 "port_id": "port-san-luis", "mmsi": "999000001"},
                {"op": "offering.upsert", "id": "c" * 32, "vessel_id": "a" * 32, "name": "Full Day"}]
        out = detect(Snapshot([old]), sent, "2026-10-05T09:47:00.000Z", complete=True,
                     history=["2026-09-01T09:47:00.000Z"], vanished_runs=3, vanished_days=45)
        changes = sorted(op["kind"] for op in out if op["op"] == "change.record")
        self.assertEqual(changes, ["mmsi", "moved", "returned", "schedule", "schedule"])
        retired = [op for op in out if op["op"] == "offering.upsert"]
        self.assertEqual([(op["id"], op["status"]) for op in retired], [("b" * 32, "retired")])

    def test_a_partial_run_retires_no_offering_of_the_failed_source(self):
        # Issue #339: "b" came from a source that failed this run; "d" from one that still lists it unchanged.
        def offering(ident, name):
            return {"id": ident, "name": name, "trip_type": "half-day", "status": "active",
                    "price_cents": 9500, "departs_local": "06:30", "days": ["sat"]}
        old = {"id": "a" * 32, "slug": "sea-example", "name": "Sea Example", "status": "active", "port_id": "morro-bay",
               "landing_id": None, "operator_id": None, "mmsi": None, "vessel_class": None,
               "last_seen_at": "2026-09-28T09:47:00.000Z",
               "offerings": [offering("b" * 32, "Half Day"), offering("d" * 32, "Twilight")]}
        sent = [{"op": "vessel.upsert", "id": "a" * 32, "slug": "sea-example", "name": "Sea Example",
                 "port_id": "morro-bay"},
                {"op": "offering.upsert", "id": "d" * 32, "vessel_id": "a" * 32, "name": "Twilight",
                 "price_cents": 9500, "departs_local": "06:30", "days_json": ["sat"]}]
        args = dict(history=["2026-09-28T09:47:00.000Z"], vanished_runs=3, vanished_days=45)
        partial = detect(Snapshot([old]), sent, "2026-10-05T09:47:00.000Z", complete=False, **args)
        self.assertEqual([op for op in partial if op["op"] == "offering.upsert"], [], "no retire op")
        self.assertEqual([op for op in partial if op.get("kind") == "schedule"], [], "no schedule change")
        complete = detect(Snapshot([old]), sent, "2026-10-05T09:47:00.000Z", complete=True, **args)
        self.assertEqual([(op["id"], op["status"]) for op in complete if op["op"] == "offering.upsert"],
                         [("b" * 32, "retired")], "a complete run still retires it")


if __name__ == "__main__":
    unittest.main()

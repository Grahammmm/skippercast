"""OSINT stale selection keeps the validated milliseconds at the cutoff (RF1036-7).

A vessel profiled strictly more than ``osint_stale_days`` before the run clock is stale, to the
millisecond that ``ops.iso`` canonicalizes to. Synthetic throughout: invented vessels, fixed clocks,
an injected snapshot loader and a temporary run directory; no sink, network or agent run.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from skippercast.fleet import agent, ops
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.resolve import Snapshot
from skippercast.fleet.runs import Run

NOW = "2026-11-14T12:00:00.500Z"
CUTOFF = "2026-09-15T12:00:00.500Z"  # NOW minus 60 days, exactly
DAYS = 60
MANIFEST_KEYS = {"manifest_version", "region", "run_id", "batch_id", "created_at", "output_dir", "output_file", "schema",
                 "validate", "policy", "boats"}


def boat(n, profiled=None, **extra):
    """A complete, active, invented vessel: only ``last_profiled_at`` (and ``extra``) decide selection."""
    row = {"id": f"ca-fixture-{n:02d}", "name": f"Fixture {n}", "status": "active", "website": f"https://boat{n}.example/",
           "mmsi": f"99900{n:04d}", "vessel_class": "six-pack", "passengers_max": 6, "port_id": "morro-bay",
           "landing_id": None, "last_profiled_at": profiled, "aliases": [],
           "offerings": [{"name": "Half Day", "status": "active"}]}
    row.update(extra)
    return row


def chosen(vessels, now=NOW, mode="refresh"):
    return [(v["id"], r) for v, r in agent.select(vessels, now, DAYS, mode)]


class CutoffTests(unittest.TestCase):
    def test_older_by_one_millisecond_is_stale(self):
        for mode in ("refresh", "full"):
            with self.subTest(mode=mode):
                self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00.499Z")], mode=mode), [("ca-fixture-01", ["stale"])])
                self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00.400Z")], mode=mode), [("ca-fixture-01", ["stale"])])
        # whole-second clock: the cutoff is 12:00:00.000, so .999 of the previous second is stale
        self.assertEqual(chosen([boat(2, "2026-09-15T11:59:59.999Z")], now="2026-11-14T12:00:00Z"),
                         [("ca-fixture-02", ["stale"])])

    def test_equal_and_newer_than_the_cutoff_are_not_stale(self):
        for profiled in (CUTOFF, "2026-09-15T12:00:00.501Z", "2026-09-15T12:00:00.600Z", "2026-09-15T12:00:01Z"):
            with self.subTest(profiled=profiled):
                self.assertEqual(chosen([boat(1, profiled)]), [])
        self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00Z")], now="2026-11-14T12:00:00Z"), [])
        self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00.001Z")], now="2026-11-14T12:00:00Z"), [])

    def test_validated_fraction_forms_have_existing_precision(self):
        before, equal = "2026-09-15T11:59:59.999Z", "2026-09-15T12:00:00Z"
        for form in ("2026-11-14T12:00:00Z", "2026-11-14T12:00:00.0Z", "2026-11-14T12:00:00.000Z"):
            with self.subTest(now=form):
                self.assertEqual(chosen([boat(1, before)], now=form), [("ca-fixture-01", ["stale"])])
                self.assertEqual(chosen([boat(1, equal)], now=form), [])
        for form in ("2026-11-14T12:00:00.5Z", "2026-11-14T12:00:00.50Z", "2026-11-14T12:00:00.500Z"):
            with self.subTest(now=form):
                self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00.499Z")], now=form), [("ca-fixture-01", ["stale"])])
                self.assertEqual(chosen([boat(1, CUTOFF)], now=form), [])
        # beyond milliseconds the existing truncation applies: .5009999 is .500, equal to the cutoff, not stale
        self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00.500999Z")]), [])
        self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00.499999Z")]), [("ca-fixture-01", ["stale"])])
        self.assertEqual(chosen([boat(1, "2026-09-15T12:00:00.500Z")], now="2026-11-14T12:00:00.500999Z"), [])

    def test_invalid_times_still_raise_the_validation_error(self):
        for bad in ("2026-02-30T12:00:00.500Z", "2026-11-14T12:00:00.500", "2026-11-14T12:00:00.500+01:00", "+01:00",
                    "", 20261114, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ops.OpError):
                    agent.select([boat(1)], bad, DAYS)
        for bad in ("2026-02-30T12:00:00.500Z", "2026-09-15T12:00:00.500", "2026-09-15T12:00:00.500+01:00", 20260915):
            with self.subTest(profiled=bad):
                with self.assertRaises(ops.OpError):
                    agent.select([boat(1, bad)], NOW, DAYS)

    def test_rank_filters_and_missing_rules_survive(self):
        vessels = [
            boat(9, "2026-09-15T12:00:00.100Z", mmsi=None),               # stale by 400 ms, also missing: stale first
            boat(3, "2026-08-01T00:00:00.000Z"),                          # stale, oldest after 5
            boat(5, "2026-07-01T00:00:00.250Z"),                          # stale, oldest
            boat(4, "2026-08-01T00:00:00Z"),                              # stale, same instant as 3: id tie-break
            boat(7),                                                      # new
            boat(2),                                                      # new, lower id first
            boat(8, "2026-11-01T00:00:00.000Z", mmsi=None),               # fresh, missing only
            boat(6, "2026-11-01T00:00:00.000Z"),                          # fresh and complete
            boat(10, CUTOFF),                                             # exactly the cutoff
            boat(11, "2026-09-15T12:00:00.100Z", status="excluded"),
            boat(12, "2026-09-15T12:00:00.100Z", status="sold"),
            boat(13, "2026-09-15T12:00:00.100Z", removal_requested=True),
            boat(14, "2026-09-15T12:00:00.100Z", removal_requested_at="2026-10-01T00:00:00.000Z"),
        ]
        shuffled = vessels[::-1]
        full = [("ca-fixture-02", ["new"]), ("ca-fixture-07", ["new"]), ("ca-fixture-05", ["stale"]),
                ("ca-fixture-03", ["stale"]), ("ca-fixture-04", ["stale"]), ("ca-fixture-09", ["stale", "missing"]),
                ("ca-fixture-08", ["missing"])]
        for order in (vessels, shuffled):
            self.assertEqual(chosen(order, mode="full"), full)
            self.assertEqual(chosen(order, mode="refresh"),
                             [("ca-fixture-02", ["new"]), ("ca-fixture-07", ["new"]), ("ca-fixture-05", ["stale"]),
                              ("ca-fixture-03", ["stale"]), ("ca-fixture-04", ["stale"]), ("ca-fixture-09", ["stale"])])
        refresh_ids = [i for i, _r in chosen(vessels, mode="refresh")]
        self.assertEqual(refresh_ids, ["ca-fixture-02", "ca-fixture-07", "ca-fixture-05", "ca-fixture-03", "ca-fixture-04",
                                       "ca-fixture-09"])
        self.assertNotIn("ca-fixture-08", refresh_ids)  # fresh missing-only boat: full mode only
        self.assertNotIn("ca-fixture-10", [i for i, _r in chosen(vessels, mode="full")])

    def test_a_fresh_missing_only_boat_is_full_mode_only(self):
        vessel = boat(1, "2026-11-01T00:00:00.000Z", mmsi=None)
        self.assertEqual(chosen([vessel], mode="full"), [("ca-fixture-01", ["missing"])])
        self.assertEqual(chosen([vessel], mode="refresh"), [])

    def test_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            agent.select([boat(1)], NOW, DAYS, "everything")


class PlanAgentBoundaryTests(unittest.TestCase):
    def test_plan_agent_persists_boundary_selection(self):
        region = SimpleNamespace(id="CA", thresholds={"refresh": {"osint_stale_days": DAYS}})
        older, equal = "2026-09-15T12:00:00.499Z", CUTOFF
        vessels = [boat(1, older), boat(2, equal)]
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("CA", "20261114T120000Z-abcdef", var=Path(tmp))
            ctx = RunContext(region=region, net=None, run_dir=run.dir, clock=lambda: NOW)
            counts = agent.plan_agent(ctx, None, mode="refresh", load=lambda sink, region_id: Snapshot(vessels))
            self.assertEqual(counts, {"vessels": 2, "selected": 1, "batches": 1, "new": 0, "stale": 1, "missing": 0})
            self.assertEqual(sorted(p.name for p in (run.dir / "manifests").iterdir()), ["batch-001.json"])
            doc = json.loads((run.dir / "manifests" / "batch-001.json").read_text(encoding="utf-8"))
            self.assertEqual(set(doc), MANIFEST_KEYS)
            self.assertEqual(doc["manifest_version"], 1)
            self.assertEqual([b["vessel_id"] for b in doc["boats"]], ["ca-fixture-01"])
            self.assertEqual(doc["boats"][0]["refresh"]["last_profiled_at"], older)
            self.assertEqual(doc["created_at"], "2026-11-14T12:00:00Z")  # created_at stays whole-second
            plan = json.loads((run.dir / "agent-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["mode"], "refresh")
            self.assertEqual(plan["stale_days"], DAYS)
            self.assertEqual(plan["at"], NOW)
            self.assertEqual(plan["counts"], counts)
            self.assertEqual(plan["batches"], ["batch-001.json"])


if __name__ == "__main__":
    unittest.main()

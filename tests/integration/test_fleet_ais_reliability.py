"""Combined historical attribution and durable aggregate replay, using synthetic offline sources."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.fleet.ais import backfill, process
from tests.unit.test_fleet_backfill import DAY, REGION, T0
from tests.unit.test_fleet_historical_targets import OTHER, SnapshotWorker, ToySource, vessel, watched
from tests.unit import test_fleet_process as process_fixture
from tests.unit.test_fleet_process import HOUR, MMSI, VESSEL


class HistoricalRemote(SnapshotWorker):
    """Reuse the aggregate fake with snapshot/watch reads and real trip derivation."""
    def __init__(self):
        super().__init__([vessel(), vessel(OTHER)], [watched()])
        self.aggregate_remote = process_fixture.AggregateRetryTests.Remote(fail_at=2)
        self.aggregate_remote.calls = self.calls
        module = process.aggregate.AggregateParams.from_region(REGION).module
        self.remotes = {(module, "2026"): self.aggregate_remote}

    def post(self, path, body):
        if "aggregates" in body:
            a = body["aggregates"]
            key = (a["module"], a["season"])
            if key not in self.remotes:
                remote = process_fixture.AggregateRetryTests.Remote()
                remote.calls = self.calls
                self.remotes[key] = remote
            return self.remotes[key].post(path, body)
        return super().post(path, body)


class FleetReliabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"
        self.worker = HistoricalRemote()
        self.now = T0 + 24 * HOUR
        self.chunk_limit = patch.object(process, "CELLS_PER_POST", 1)
        self.chunk_limit.start()
        self.addCleanup(self.chunk_limit.stop)

    def raw_hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (self.root / "backfill" / "raw").glob("*.sqlite")}

    def state_snapshot(self):
        state = process.State(self.root / "state.sqlite")
        try:
            return state.aggregate_rebuilds(), state.cells("2026"), state.season_events("2026")
        finally:
            state.close()

    def start_interrupted_backfill(self):
        with self.assertRaisesRegex(process.WorkerError, "interrupted"):
            backfill.backfill(REGION, self.worker, root=self.root, first=DAY, last=DAY,
                              source=ToySource(), now_ms=self.now, allow_prune=True)
        pending, digests, events = self.state_snapshot()
        self.assertEqual(pending, {"2026": process.aggregate.AggregateParams.from_region(REGION).module})
        self.assertEqual(digests, {})
        self.assertTrue(events, "real derived events survive the interrupted upload")
        raw = self.raw_hashes()
        self.assertTrue(raw)
        self.assertIn("stale", self.worker.aggregate_remote.remote)
        self.worker.aggregate_remote.fail_at = None
        return raw

    def assert_complete(self, stamp, raw):
        pending, digests, events = self.state_snapshot()
        remote = self.worker.aggregate_remote.remote
        self.assertEqual(pending, {})
        self.assertEqual(set(remote), set(digests))
        self.assertEqual(len(remote), 2, "the real synthetic fishing event occupies two cells")
        self.assertEqual({c["computed_at"] for c in remote.values()}, {process.iso_utc(stamp)})
        self.assertEqual({c["rights"] for c in remote.values()}, {"noaa-planning-only"})
        self.assertEqual({e.vessel_id for e in events}, {VESSEL})
        self.assertEqual(self.raw_hashes(), raw)
        self.assertFalse((self.root / "raw").exists(), "historical processing leaves listener storage alone")
        self.assertFalse(any(method == "POST" and path != "activity"
                             for method, path, _ in self.worker.calls))
        old_season = [p["aggregates"] for p in self.worker.posts("activity", "aggregates")
                      if p["aggregates"]["season"] == "2026"]
        self.assertEqual(old_season[-1]["prune"],
                         process.iso_utc(stamp))

    def test_watch_only_backfill_restarts_authorized_rebuild_without_new_prune_flag(self):
        raw = self.start_interrupted_backfill()
        source = ToySource()
        result = backfill.backfill(REGION, self.worker, root=self.root, first=DAY, last=DAY,
                                   source=source, now_ms=self.now + HOUR)
        self.assertEqual(source.calls, [], "the retained day manifest avoids downloading again")
        self.assertEqual(result["processed"]["trips"]["trips"], 1)
        self.assertEqual(result["processed"]["aggregates"]["requests"], 2)
        self.assertEqual({t["vessel_id"] for p in self.worker.posts("activity", "replace")
                          for t in p["trips"]}, {VESSEL})
        self.assert_complete(self.now + HOUR, raw)

    def test_changed_identity_cannot_use_pending_rebuild_to_bypass_preflight(self):
        raw = self.start_interrupted_backfill()
        selected = process.historical_targets(self.worker, "CA")
        self.worker.rows = [watched(ident=OTHER)]
        before = len(self.worker.posts("activity"))
        with self.assertRaisesRegex(ValueError, "selection changed"):
            process.run(REGION, self.worker, root=self.root, source="marinecadastre",
                        window=backfill.window_ms(DAY, DAY, REGION.timezone), now_ms=self.now + HOUR,
                        mmsis=[MMSI], expected_targets=selected)
        self.assertEqual(len(self.worker.posts("activity")), before)
        self.assertTrue(self.state_snapshot()[0], "identity rejection must retain pending prune intent")
        self.assertEqual(self.raw_hashes(), raw)
        self.worker.rows = [watched()]
        process.run(REGION, self.worker, root=self.root, source="marinecadastre",
                    window=backfill.window_ms(DAY, DAY, REGION.timezone), now_ms=self.now + 2 * HOUR,
                    mmsis=[MMSI], expected_targets=selected)
        self.assert_complete(self.now + 2 * HOUR, raw)

    def test_empty_later_window_still_finishes_an_earlier_pending_season(self):
        raw = self.start_interrupted_backfill()
        later = process._ms("2027-01-07T00:00:00Z")
        with patch.object(process, "push_aggregates", wraps=process.push_aggregates) as upload:
            result = process.run(REGION, self.worker, root=self.root, source="marinecadastre",
                                 window=(later, later + HOUR), now_ms=later + 24 * HOUR, mmsis=[MMSI])
        self.assertEqual(result["trips"]["trips"], 0)
        self.assertEqual(upload.call_args.args[1], {"2027"}, "this run does not touch the pending 2026 season")
        self.assertEqual(result["aggregates"]["requests"], 3, "two old-season chunks and one empty later season")
        self.assert_complete(later + 24 * HOUR, raw)


if __name__ == "__main__":
    unittest.main()

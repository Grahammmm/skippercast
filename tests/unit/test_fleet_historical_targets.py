"""Historical targets use existing registry/watch decisions; all identities and raw tracks are synthetic."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.fleet.ais import backfill, process
from skippercast.fleet.ais.store import AisStore
from skippercast.fleet.ops import id32
from tests.unit.test_fleet_process import FakeWorker, HOUR, MMSI, REGION, T0, VESSEL, track
from tests.unit.test_fleet_backfill import DAY as BACKFILL_DAY, REGION as BACKFILL_REGION, T0 as BACKFILL_T0

OTHER = id32("CA", "historical-other")
SECOND_MMSI = 999000456


def vessel(ident=VESSEL, mmsi=None, **extra):
    return {"id": ident, "mmsi": None if mmsi is None else str(mmsi), "status": "active",
            "name": "Synthetic History Boat", "port_id": "port-a", "vessel_class": "inspected-party", **extra}


def watched(mmsi=MMSI, ident=VESSEL, **extra):
    return {"mmsi": str(mmsi), "vessel_id": ident, "status": "watched", "match_method": "geofence-presence",
            "confidence": 0.85, **extra}


class SnapshotWorker(FakeWorker):
    def __init__(self, vessels, rows=(), reviews=(), page_size=100):
        super().__init__(vessels=vessels)
        self.rows, self.reviews, self.page_size = list(rows), list(reviews), page_size

    def get(self, path, **params):
        self.calls.append(("GET", path, params))
        if path == "snapshot":
            section, after = params.get("cursor", "v:").split(":")
            data = self.vessels if section == "v" else self.reviews
            start = int(after or 0)
            end = start + self.page_size
            following = f"{section}:{end}" if len(data) > end else "r:" if section == "v" else None
            return {"vessels" if section == "v" else "reviews": data[start:end], "next": following}
        if path == "watch":
            data = [r for r in self.rows if params.get("status") in (None, r["status"])]
            start = int(params.get("cursor") or 0)
            end = start + self.page_size
            return {"rows": data[start:end], "next": str(end) if len(data) > end else None}
        raise AssertionError(path)


class ToySource:
    def __init__(self, on_first=None):
        self.calls, self.on_first = [], on_first

    def history(self, day, bbox, mmsis, counts):
        self.calls.append((day, set(mmsis)))
        if len(self.calls) == 1 and self.on_first:
            self.on_first()
        for position in track(t0=BACKFILL_T0):
            if position.mmsi in mmsis and datetime.fromtimestamp(position.ts / 1000, timezone.utc).date() == day:
                yield replace(position, source="marinecadastre")


class HistoricalTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"

    def test_window_uses_the_same_stored_watch_identity_as_the_live_match_hook(self):
        AisStore(self.root).write(positions=track())
        worker = SnapshotWorker([vessel()], [watched()])
        hooks = {"match": lambda ctx: {MMSI: process.VesselRef(VESSEL, "inspected-party", "port-a")}}
        live = process.run(REGION, worker, root=self.root, now_ms=T0 + 24 * HOUR, hook_table=hooks)
        worker.calls.clear()
        raw_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root / "raw").glob("*.sqlite")}
        watch_file = self.root / "watch.json"
        watch_file.write_text("synthetic listener sentinel")
        rerun = process.run(REGION, worker, root=self.root, now_ms=T0 + 24 * HOUR,
                            window=(T0 - HOUR, T0 + 12 * HOUR), hook_table=hooks)
        self.assertEqual((live["trips"]["vessels"], live["trips"]["trips"]), (1, 1))
        self.assertEqual((rerun["trips"]["vessels"], rerun["trips"]["trips"]), (1, 1))
        self.assertEqual({t["vessel_id"] for p in worker.posts("activity", "replace") for t in p["trips"]}, {VESSEL})
        self.assertEqual(watch_file.read_text(), "synthetic listener sentinel")
        self.assertEqual({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root / "raw").glob("*.sqlite")}, raw_hashes)
        self.assertFalse(any(method == "POST" and path in ("watch", "registry", "heartbeat") for method, path, _ in worker.calls))

    def test_default_and_explicit_backfill_process_the_approved_watch_only_vessel(self):
        for explicit in (None, [MMSI]):
            with self.subTest(explicit=explicit):
                root = self.root / str(explicit is not None)
                worker, source = SnapshotWorker([vessel()], [watched()]), ToySource()
                result = backfill.backfill(BACKFILL_REGION, worker, root=root, first=BACKFILL_DAY, last=BACKFILL_DAY,
                                           source=source, mmsis=explicit, now_ms=BACKFILL_T0 + 24 * HOUR)
                self.assertEqual((result["mmsis"], result["processed"]["trips"]["vessels"],
                                  result["processed"]["trips"]["trips"]), (1, 1, 1))
                self.assertTrue(source.calls)
                self.assertTrue(all(ids == {MMSI} for _, ids in source.calls))
                rows = [t for p in worker.posts("activity", "replace") for t in p["trips"] + p["events"]]
                self.assertTrue(rows)
                self.assertEqual({(r["source"], r["rights"], r["vessel_id"]) for r in rows},
                                 {("marinecadastre", "noaa-planning-only", VESSEL)})
                self.assertFalse((root / "raw").exists(), "backfill never writes the listener raw store")
                self.assertFalse(any(method == "POST" and path != "activity" for method, path, _ in worker.calls))

    def test_unresolved_explicit_backfill_targets_fail_before_ingestion(self):
        worker, source = SnapshotWorker([vessel()], [watched()]), ToySource()
        with self.assertRaisesRegex(ValueError, "approved"):
            backfill.backfill(BACKFILL_REGION, worker, root=self.root, first=BACKFILL_DAY, last=BACKFILL_DAY,
                              source=source, mmsis=[MMSI, SECOND_MMSI], now_ms=BACKFILL_T0 + 24 * HOUR)
        self.assertEqual(source.calls, [])
        self.assertEqual(worker.posts("activity"), [])

    def test_unresolved_explicit_rerun_target_fails_before_activity_writes(self):
        worker = SnapshotWorker([vessel()], [watched()])
        with self.assertRaisesRegex(ValueError, "approved"):
            process.run(REGION, worker, root=self.root, now_ms=T0 + 24 * HOUR,
                        window=(T0, T0 + HOUR), mmsis=[SECOND_MMSI])
        self.assertEqual(worker.posts("activity"), [])

    def test_backfill_stops_if_approved_attribution_changes_during_download(self):
        worker = SnapshotWorker([vessel(), vessel(OTHER)], [watched()])
        source = ToySource(on_first=lambda: worker.rows.__setitem__(0, watched(ident=OTHER)))
        with self.assertRaisesRegex(ValueError, "selection changed"):
            backfill.backfill(BACKFILL_REGION, worker, root=self.root, first=BACKFILL_DAY, last=BACKFILL_DAY,
                              source=source, now_ms=BACKFILL_T0 + 24 * HOUR)
        self.assertTrue(source.calls, "an initially approved target was ingested")
        self.assertEqual(worker.posts("activity"), [], "changed attribution cannot be posted")
        self.assertTrue(list((self.root / "backfill" / "raw").glob("*.sqlite")), "preserve acquired source rows")

    def test_paginated_registry_watch_and_rejections_are_read_completely(self):
        third = id32("CA", "historical-third")
        reviews = [{"kind": "mmsi", "status": "dismissed"},
                   {"kind": "mmsi", "status": "decided", "subject_id": OTHER,
                    "decision": {"action": "reject-mmsi", "mmsi": str(SECOND_MMSI)}}]
        worker = SnapshotWorker([vessel(), vessel(OTHER), vessel(third, 999000789)],
                                [watched(), watched(SECOND_MMSI, OTHER)], reviews, page_size=1)
        selected = process.historical_targets(worker, "CA")
        self.assertEqual(selected, {MMSI: process.VesselRef(VESSEL, "inspected-party", "port-a"),
                                    999000789: process.VesselRef(third, "inspected-party", "port-a")})
        self.assertTrue(any(path == "watch" and p.get("cursor") for _, path, p in worker.calls))
        self.assertTrue(any(path == "snapshot" and p["cursor"].startswith("r:") for _, path, p in worker.calls))

    def test_registry_precedence_exclusions_duplicates_and_own_mmsi_conflicts(self):
        duplicate = id32("CA", "historical-duplicate")
        excluded = id32("CA", "historical-excluded")
        workers = [
            (SnapshotWorker([vessel(mmsi=MMSI), vessel(OTHER)], [watched(ident=OTHER)]), {MMSI: VESSEL}),
            (SnapshotWorker([vessel(mmsi=MMSI), vessel(OTHER, MMSI), vessel(duplicate)],
                            [watched(ident=duplicate)]), {}),
            (SnapshotWorker([vessel(status="excluded")], [watched()]), {}),
            (SnapshotWorker([vessel(), vessel(excluded, MMSI, status="excluded")], [watched()]), {MMSI: VESSEL}),
            (SnapshotWorker([vessel(mmsi=SECOND_MMSI)], [watched()]), {SECOND_MMSI: VESSEL}),
            (SnapshotWorker([vessel()], [watched(ident=OTHER)]), {}),
        ]
        for worker, expected in workers:
            with self.subTest(expected=expected, rows=worker.rows):
                self.assertEqual({m: r.vessel_id for m, r in process.historical_targets(worker, "CA").items()}, expected)

    def test_only_strong_finite_approved_watch_rows_are_selected(self):
        cases = [dict(status="candidate"), dict(status="rejected"), dict(match_method="call-sign", confidence=1),
                 dict(match_method="ais-static-name", confidence=1), dict(confidence=0.849), dict(confidence=None),
                 dict(confidence=True), dict(confidence=float("nan")), dict(confidence=float("inf")),
                 dict(confidence=1.01), dict(match_method="admin"), dict(mmsi="0"), dict(mmsi="99900012x")]
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertEqual(process.historical_targets(SnapshotWorker([vessel()], [watched(**extra)]), "CA"), {})
        for method in ("geofence-presence", "schedule-correlation", "fcc-uls"):
            self.assertIn(MMSI, process.historical_targets(
                SnapshotWorker([vessel()], [watched(match_method=method)]), "CA"))

    def test_duplicate_watch_bindings_are_not_guessed(self):
        worker = SnapshotWorker([vessel(), vessel(OTHER)], [watched(), watched(ident=OTHER)])
        self.assertEqual(process.historical_targets(worker, "CA"), {})

    def test_inconsistent_duplicate_vessel_pages_do_not_supply_a_watch_attribution(self):
        for vessels in ([vessel(), vessel(port_id="different-port")],
                        [vessel(mmsi=SECOND_MMSI), vessel()], [vessel(mmsi="invalid")]):
            with self.subTest(vessels=vessels):
                selected = process.historical_targets(SnapshotWorker(vessels, [watched()], page_size=1), "CA")
                self.assertNotIn(MMSI, selected)

    def test_explicit_selection_does_not_acquire_new_targets_mid_backfill(self):
        worker = SnapshotWorker([vessel(), vessel(OTHER)], [watched()])
        source = ToySource(on_first=lambda: worker.rows.append(watched(SECOND_MMSI, OTHER)))
        result = backfill.backfill(BACKFILL_REGION, worker, root=self.root, first=BACKFILL_DAY, last=BACKFILL_DAY,
                                   source=source, now_ms=BACKFILL_T0 + 24 * HOUR)
        self.assertEqual(result["mmsis"], 1)
        self.assertTrue(all(ids == {MMSI} for _, ids in source.calls))
        self.assertEqual({t["mmsi"] for p in worker.posts("activity", "replace") for t in p["trips"]}, {str(MMSI)})

    def test_registry_only_historical_run_survives_optional_match_module_absence(self):
        with patch.dict("sys.modules", {"skippercast.fleet.ais.match": None}):
            selected = process.historical_targets(SnapshotWorker([vessel(mmsi=MMSI)]), "CA")
        self.assertEqual(selected, {MMSI: process.VesselRef(VESSEL, "inspected-party", "port-a")})


if __name__ == "__main__":
    unittest.main()

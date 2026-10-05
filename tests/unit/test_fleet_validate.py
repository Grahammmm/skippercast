"""skippercast.fleet.ais.validate: the classifier's validation against hand labels (CF-48, design.md section 11).

Synthetic throughout: the processor tests' made-up MMSI (999xxxxxx) and square
harbor drawn in open ocean, a raw store under a temporary FLEET_VAR, made-up
labeller ids (``admin-test``, ``agent:test``) and a fake Worker serving the
labels the admin view would have stored.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.fleet.ais import validate
from skippercast.fleet.ais.events import iso_utc
from skippercast.fleet.ais.process import HOUR, MINUTE
from skippercast.fleet.ais.segment import ActivityThresholds
from skippercast.fleet.ais.store import AisStore, retention_limits
from skippercast.fleet.ais.validate import Interval, confusion, metrics, score
from skippercast.fleet.ops import id32
from tests._support import ROOT
from tests.unit.test_fleet_process import MMSI, REGION, T0, VESSEL, track

M = MINUTE
TRIP = id32(str(MMSI), iso_utc(T0 + 39 * M), "aisstream")
OTHER = "f" * 32


def label(start_min, end_min, kind, labeller="admin-test", basis="track shape"):
    return {"id": id32("label", str(start_min), kind), "started_at": iso_utc(T0 + start_min * M),
            "ended_at": iso_utc(T0 + end_min * M), "label": kind, "labeller": labeller, "basis": basis,
            "created_at": iso_utc(T0 + 9 * HOUR)}


# How the synthetic track was built (test_fleet_process.track): in port to 30 min, transit to 55, drift to 95,
# troll to 125, then home. A person who knew that would label it so.
LABELS = [label(30, 55, "transit"), label(55, 95, "fishing-drift"), label(95, 125, "fishing-troll", "agent:test", "skipper's log")]


def trip_row(trip_id=TRIP, labels=LABELS, returned=T0 + 140 * M, source="aisstream"):
    return {"id": trip_id, "mmsi": str(MMSI), "vessel_id": VESSEL, "source": source, "departed_at": iso_utc(T0 + 39 * M),
            "returned_at": None if returned is None else iso_utc(returned), "status": "closed", "depart_port_id": "port-a",
            "labels": list(labels)}


class LabelWorker:
    """Serves GET labels in pages of `page` trips, as /api/fleet/jobs/labels does."""

    def __init__(self, trips, page=1):
        self.trips, self.page, self.calls = sorted(trips, key=lambda t: t["id"]), page, []

    def get(self, path, **params):
        self.calls.append((path, params))
        assert path == "labels", path
        rest = [t for t in self.trips if t["id"] > params.get("cursor", "")]
        chunk = rest[:self.page]
        return {"region": params["region"], "trips": chunk, "next": chunk[-1]["id"] if len(rest) > self.page else None}


class ScoringTests(unittest.TestCase):
    def test_acceptance_1_precision_and_recall_match_hand_computed_values(self):
        """Labels: drift 0-40, transit 40-60, troll 60-90, in port 90-100 (minutes).
        Classifier: transit 0-10, drift 10-50, troll 50-80, gap 80-85, transit 85-90, nothing after 90.

        By hand: drift row = transit 10, drift 30; transit row = drift 10, troll 10; troll row = troll 20,
        gap 5 (not scored), transit 5; in-port row = none 10.
        drift  P = 30 / (30 + 10) = 0.75     R = 30 / 40 = 0.75
        troll  P = 20 / (10 + 20) = 0.667    R = 20 / 25 = 0.8
        transit P = 0 / 15 = 0               R = 0 / 20 = 0
        in-port P = none predicted (null)    R = 0 / 10 = 0
        fishing: agree 30 + 20 = 50; predicted 30 + 20 (transit labelled) + 20 = 70; labelled 40 + 25 = 65
                 P = 50 / 70 = 0.714, R = 50 / 65 = 0.769
        """
        labels = [Interval(0, 40 * M, "fishing-drift"), Interval(40 * M, 60 * M, "transit"),
                  Interval(60 * M, 90 * M, "fishing-troll"), Interval(90 * M, 100 * M, "in-port")]
        predictions = [Interval(0, 10 * M, "transit"), Interval(10 * M, 50 * M, "fishing-drift"),
                       Interval(50 * M, 80 * M, "fishing-troll"), Interval(80 * M, 85 * M, "gap"),
                       Interval(85 * M, 90 * M, "transit")]
        r = score(labels, predictions)
        self.assertEqual(r["confusion"]["fishing-drift"], {"in-port": 0, "transit": 10, "fishing-drift": 30, "fishing-troll": 0, "gap": 0, "none": 0})
        self.assertEqual(r["confusion"]["transit"], {"in-port": 0, "transit": 0, "fishing-drift": 10, "fishing-troll": 10, "gap": 0, "none": 0})
        self.assertEqual(r["confusion"]["fishing-troll"], {"in-port": 0, "transit": 5, "fishing-drift": 0, "fishing-troll": 20, "gap": 5, "none": 0})
        self.assertEqual(r["confusion"]["in-port"], {"in-port": 0, "transit": 0, "fishing-drift": 0, "fishing-troll": 0, "gap": 0, "none": 10})
        self.assertEqual(r["minutes"], {"labelled": 100, "scored": 95, "gap_unscored": 5})
        self.assertEqual(r["fishing"], {"labelled_min": 65, "predicted_min": 70, "agree_min": 50, "precision": 0.714, "recall": 0.769})
        k = r["kinds"]
        self.assertEqual((k["fishing-drift"]["precision"], k["fishing-drift"]["recall"]), (0.75, 0.75))
        self.assertEqual((k["fishing-troll"]["precision"], k["fishing-troll"]["recall"]), (0.667, 0.8))
        self.assertEqual((k["transit"]["precision"], k["transit"]["recall"]), (0.0, 0.0))
        self.assertEqual((k["in-port"]["precision"], k["in-port"]["recall"]), (None, 0.0))

    def test_whole_minutes_inside_a_label_count_once(self):
        # 00:30 to 03:00 holds the minutes starting 01:00 and 02:00; a second label over 02:00 does not count it again.
        table = confusion([Interval(30_000, 3 * M, "transit"), Interval(2 * M, 4 * M, "fishing-drift")],
                          [Interval(0, 10 * M, "transit")])
        self.assertEqual(table["transit"]["transit"], 2)
        self.assertEqual(table["fishing-drift"]["transit"], 1)
        with self.assertRaises(ValueError):
            confusion([Interval(0, M, "fishing")], [])

    def test_a_drift_minute_predicted_troll_is_still_fishing(self):
        r = score([Interval(0, 10 * M, "fishing-drift")], [Interval(0, 10 * M, "fishing-troll")])
        self.assertEqual((r["fishing"]["precision"], r["fishing"]["recall"]), (1.0, 1.0))
        self.assertEqual(r["kinds"]["fishing-drift"]["recall"], 0.0)

    def test_no_labels_give_no_ratios(self):
        r = metrics(confusion([], [Interval(0, M, "transit")]))
        self.assertEqual((r["fishing"]["precision"], r["fishing"]["recall"]), (None, None))


class SyncTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"
        self.store = AisStore(self.root)
        self.store.write(positions=track())
        self.copy = self.root / "validation" / f"{TRIP}.sqlite"


class SyncTests(SyncTestCase):
    def test_labelled_trips_are_copied_with_their_labels_paging_by_trip_id(self):
        other = trip_row(OTHER, [label(0, 10, "in-port")], source="datalastic")   # no raw store for it here
        worker = LabelWorker([trip_row(), other], page=1)
        counts = validate.sync(REGION, worker, self.root, now_ms=T0 + 8 * HOUR)
        self.assertEqual([p.get("cursor") for _, p in worker.calls], [None, TRIP])
        self.assertEqual(counts, {"trips": 2, "copied": 1, "positions": len(track()), "empty": 0, "unsupported": 1, "orphaned": 0, "removed": 0})
        self.assertEqual(validate.read_copy(self.copy), list(self.store.read_positions(0, 2**62, [MMSI])))
        stored = json.loads((self.root / "validation" / "labels.json").read_text())
        self.assertEqual([t["id"] for t in stored["trips"]], [TRIP, OTHER])
        # Acceptance 2: every label carries its labeller and basis.
        for row in stored["trips"][0]["labels"]:
            self.assertTrue(row["labeller"] and row["basis"])
        again = validate.sync(REGION, LabelWorker([trip_row()]), self.root, now_ms=T0 + 9 * HOUR)
        self.assertEqual(again["positions"], len(track()), "a second sync adds nothing twice")

    def test_a_trip_without_raw_positions_left_is_reported_empty(self):
        late = trip_row(id32("x"), [label(0, 30, "transit")])
        late["departed_at"], late["returned_at"] = iso_utc(T0 + 30 * 24 * HOUR), iso_utc(T0 + 30 * 24 * HOUR + HOUR)
        counts = validate.sync(REGION, LabelWorker([late]), self.root, now_ms=T0 + 31 * 24 * HOUR)
        self.assertEqual((counts["copied"], counts["empty"]), (1, 1))

    def test_acceptance_3_labelled_raw_data_is_exempt_from_retention_while_the_label_exists(self):
        validate.sync(REGION, LabelWorker([trip_row()]), self.root, now_ms=T0 + 8 * HOUR)
        before = validate.report(REGION, self.root, now_ms=T0 + 8 * HOUR)
        # 40 days on, retention has emptied the day's positions (raw_days 30); the validation copy is untouched.
        result = self.store.apply_retention(retention_limits(REGION), today=self._day(T0 + 40 * 24 * HOUR))
        self.assertEqual(result.emptied, {"2026-10-05.sqlite": ["positions"]})
        self.assertEqual(list(self.store.read_positions(0, 2**62)), [])
        self.assertEqual(len(validate.read_copy(self.copy)), len(track()))
        # The next sync (raw positions gone) keeps the copy whole, and scoring still works from it.
        counts = validate.sync(REGION, LabelWorker([trip_row()]), self.root, now_ms=T0 + 40 * 24 * HOUR)
        self.assertEqual(counts["positions"], len(track()))
        after = validate.report(REGION, self.root, now_ms=T0 + 8 * HOUR)
        self.assertEqual({k: v for k, v in after.items() if k != "computed_at"}, {k: v for k, v in before.items() if k != "computed_at"})
        # A re-run that replaces the trip under another id leaves its labels as an orphan: the copy stays and is scored.
        orphan = {"id": TRIP, "mmsi": None, "vessel_id": None, "source": None, "departed_at": None, "returned_at": None,
                  "status": None, "depart_port_id": None, "orphan": True, "labels": LABELS}
        elsewhere = {**orphan, "id": OTHER}   # another region's orphan: no copy here, not counted
        counts = validate.sync(REGION, LabelWorker([orphan, elsewhere]), self.root, now_ms=T0 + 40 * 24 * HOUR)
        self.assertEqual((counts["orphaned"], counts["removed"], counts["copied"]), (2, 0, 0))
        self.assertEqual(len(validate.read_copy(self.copy)), len(track()))
        kept = validate.report(REGION, self.root, now_ms=T0 + 8 * HOUR)
        self.assertEqual(kept["fishing"], before["fishing"])
        self.assertEqual(kept["trips"], {"scored": 1, "missing": 0, "ports": 0})
        # Once the trip has no label left, its copy goes.
        (self.root / "validation" / f"{TRIP}.sqlite-wal").write_bytes(b"")
        (self.root / "validation" / "notes.txt").write_text("kept")
        counts = validate.sync(REGION, LabelWorker([]), self.root, now_ms=T0 + 41 * 24 * HOUR)
        self.assertEqual(counts["removed"], 1)
        self.assertFalse(self.copy.exists())
        self.assertFalse((self.root / "validation" / f"{TRIP}.sqlite-wal").exists())
        self.assertTrue((self.root / "validation" / "notes.txt").exists(), "only trip copies are removed")

    @staticmethod
    def _day(ms):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


class ReportTests(SyncTestCase):
    def setUp(self):
        super().setUp()
        validate.sync(REGION, LabelWorker([trip_row()]), self.root, now_ms=T0 + 8 * HOUR)

    def test_the_report_scores_the_copy_like_the_processor_would(self):
        r = validate.report(REGION, self.root, now_ms=T0 + 8 * HOUR)
        th = ActivityThresholds.from_region(REGION)
        expected = score([Interval(validate._ms(x["started_at"]), validate._ms(x["ended_at"]), x["label"]) for x in LABELS],
                         validate.predict(track(), REGION.ports, th))
        for key in ("minutes", "fishing", "kinds", "confusion"):
            self.assertEqual(r[key], expected[key], key)
        self.assertEqual(r["trips"], {"scored": 1, "missing": 0, "ports": 1})
        self.assertEqual(r["labels"], {"admin": 2, "agent": 1})
        self.assertEqual(r["basis"], "inferred-from-movement")
        self.assertFalse(r["target"]["met"], "one trip is short of the 30-trip target")
        self.assertEqual((r["target"]["trips"], r["target"]["fishing_precision"], r["target"]["fishing_recall"]), (30, 0.8, 0.7))
        self.assertGreater(r["fishing"]["agree_min"], 0)

    def test_one_labeller_kind_and_other_thresholds(self):
        agent = validate.report(REGION, self.root, labeller="agent", now_ms=T0)
        self.assertEqual(agent["labels"], {"agent": 1})
        self.assertEqual(agent["kinds"]["fishing-drift"]["labelled_min"], 0)
        self.assertEqual(agent["minutes"]["labelled"], 30)
        override = Path(self.tmp.name) / "th.json"
        override.write_text(json.dumps({"drift": {"max_sog_kn": 0.1}}))
        th = validate._thresholds(REGION, str(override))
        self.assertEqual(th.drift_max_sog_kn, 0.1)
        self.assertEqual(th.troll_max_sog_kn, ActivityThresholds.from_region(REGION).troll_max_sog_kn)
        retested = validate.report(REGION, self.root, thresholds=th, now_ms=T0)
        self.assertNotEqual(retested["classifier_version"], validate.report(REGION, self.root, now_ms=T0)["classifier_version"])
        self.assertEqual(retested["kinds"]["fishing-drift"]["agree_min"], 0, "no fix drifts under 0.1 kn")

    def test_a_trip_without_a_copy_is_missing(self):
        self.copy.unlink()
        r = validate.report(REGION, self.root, now_ms=T0)
        self.assertEqual(r["trips"], {"scored": 0, "missing": 1, "ports": 0})

    def test_markdown_holds_aggregates_only(self):
        text = validate.markdown(validate.report(REGION, self.root, now_ms=T0))
        self.assertIn("Fishing precision", text)
        self.assertIn("inferred from movement", text)
        self.assertIn("never confirmed fishing", text)
        for secret in (str(MMSI), TRIP, "admin-test", "agent:test", VESSEL):
            self.assertNotIn(secret, text)

    def test_the_command_line_scores_offline_and_writes_the_report(self):
        var = Path(self.tmp.name) / "var"
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(var)}):
            self.assertEqual(validate.main(["--region", "CA", "--offline"]), 0)
        written = json.loads((var / "CA" / "ais" / "validation" / "report.json").read_text())
        self.assertEqual(written["trips"], {"scored": 0, "missing": 0, "ports": 0})
        self.assertTrue((var / "CA" / "ais" / "validation" / "report.md").read_text().startswith("## AIS classification validation, CA"))


class WiringTests(unittest.TestCase):
    def test_the_processor_workflow_copies_after_each_scheduled_run(self):
        text = (ROOT / ".github" / "workflows" / "fleet-ais.yml").read_text()
        self.assertIn('python -m skippercast.fleet.ais validate --region "$REGION" --sync-only', text)
        process = text.index("python -m skippercast.fleet.ais process")
        self.assertLess(process, text.index("--sync-only"))
        from skippercast.fleet.ais.__main__ import COMMANDS
        self.assertIn("validate", COMMANDS)


if __name__ == "__main__":
    unittest.main()

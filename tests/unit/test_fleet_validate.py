"""skippercast.fleet.ais.validate: the classifier's validation against hand labels (CF-48, design.md section 11).

Synthetic throughout: the processor tests' made-up MMSI (999xxxxxx) and square
harbor drawn in open ocean, a raw store under a temporary FLEET_VAR, made-up
labeller ids (``admin-test``, ``agent:test``) and a fake Worker serving the
labels the admin view would have stored and taking the labels ``label import`` posts.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.fleet.ais import label as labelling, validate
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
LABELS = [label(30, 55, "transit"), label(55, 95, "drift-anchor"), label(95, 125, "troll-pelagic", "agent:test", "skipper's log")]


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

    def post(self, path, body):
        self.calls.append((path, body))
        assert path == "labels", path
        return {"trip_id": body["trip_id"], "labels": len(body["labels"])}


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
        labels = [Interval(0, 40 * M, "drift-anchor"), Interval(40 * M, 60 * M, "transit"),
                  Interval(60 * M, 90 * M, "troll-slow"), Interval(90 * M, 100 * M, "in-port")]
        predictions = [Interval(0, 10 * M, "transit"), Interval(10 * M, 50 * M, "drift-anchor"),
                       Interval(50 * M, 80 * M, "troll-slow"), Interval(80 * M, 85 * M, "gap"),
                       Interval(85 * M, 90 * M, "transit")]
        r = score(labels, predictions)
        self.assertEqual(r["confusion"]["drift-anchor"], {"in-port": 0, "transit": 10, "drift-anchor": 30, "troll-slow": 0, "troll-pelagic": 0, "uncertain": 0, "gap": 0, "none": 0})
        self.assertEqual(r["confusion"]["transit"], {"in-port": 0, "transit": 0, "drift-anchor": 10, "troll-slow": 10, "troll-pelagic": 0, "uncertain": 0, "gap": 0, "none": 0})
        self.assertEqual(r["confusion"]["troll-slow"], {"in-port": 0, "transit": 5, "drift-anchor": 0, "troll-slow": 20, "troll-pelagic": 0, "uncertain": 0, "gap": 5, "none": 0})
        self.assertEqual(r["confusion"]["in-port"], {"in-port": 0, "transit": 0, "drift-anchor": 0, "troll-slow": 0, "troll-pelagic": 0, "uncertain": 0, "gap": 0, "none": 10})
        self.assertEqual(r["minutes"], {"labelled": 100, "scored": 95, "gap_unscored": 5})
        self.assertEqual(r["fishing"], {"labelled_min": 65, "predicted_min": 70, "agree_min": 50, "precision": 0.714, "recall": 0.769})
        k = r["kinds"]
        self.assertEqual((k["drift-anchor"]["precision"], k["drift-anchor"]["recall"]), (0.75, 0.75))
        self.assertEqual((k["troll-slow"]["precision"], k["troll-slow"]["recall"]), (0.667, 0.8))
        self.assertEqual((k["transit"]["precision"], k["transit"]["recall"]), (0.0, 0.0))
        self.assertEqual((k["in-port"]["precision"], k["in-port"]["recall"]), (None, 0.0))

    def test_whole_minutes_inside_a_label_count_once(self):
        # 00:30 to 03:00 holds the minutes starting 01:00 and 02:00; a second label over 02:00 does not count it again.
        table = confusion([Interval(30_000, 3 * M, "transit"), Interval(2 * M, 4 * M, "drift-anchor")],
                          [Interval(0, 10 * M, "transit")])
        self.assertEqual(table["transit"]["transit"], 2)
        self.assertEqual(table["drift-anchor"]["transit"], 1)
        with self.assertRaises(ValueError):
            confusion([Interval(0, M, "fishing")], [])

    def test_a_drift_minute_predicted_troll_is_still_fishing(self):
        r = score([Interval(0, 10 * M, "drift-anchor")], [Interval(0, 10 * M, "troll-slow")])
        self.assertEqual((r["fishing"]["precision"], r["fishing"]["recall"]), (1.0, 1.0))
        self.assertEqual(r["kinds"]["drift-anchor"]["recall"], 0.0)

    def test_no_labels_give_no_ratios(self):
        r = metrics(confusion([], [Interval(0, M, "transit")]))
        self.assertEqual((r["fishing"]["precision"], r["fishing"]["recall"]), (None, None))

    def test_the_target_also_needs_each_fishing_mode(self):
        labels = [Interval(0, 50 * M, "drift-anchor"), Interval(50 * M, 100 * M, "troll-slow"),
                  Interval(100 * M, 150 * M, "troll-pelagic")]
        # Slow troll called pelagic: still fishing, so the overall gate passes, but troll-slow's recall is 0
        # and troll-pelagic's precision 0.5.
        mixed = score(labels, [Interval(0, 50 * M, "drift-anchor"), Interval(50 * M, 150 * M, "troll-pelagic")])
        t = validate.target(mixed, 30)
        self.assertTrue(t["overall_met"])
        self.assertFalse(t["met"])
        self.assertEqual(t["per_mode"], {"drift-anchor": {"precision": 1.0, "recall": 1.0, "met": True},
                                         "troll-slow": {"precision": None, "recall": 0.0, "met": False},
                                         "troll-pelagic": {"precision": 0.5, "recall": 1.0, "met": False}})
        right = score(labels, labels)
        self.assertTrue(validate.target(right, 30)["met"])
        short = validate.target(right, 29)
        self.assertEqual((short["overall_met"], short["met"]), (False, False))
        self.assertTrue(all(v["met"] for v in short["per_mode"].values()))
        no_pelagic = score(labels[:2], labels[:2])
        self.assertFalse(validate.target(no_pelagic, 30)["met"], "a mode never labelled cannot pass")

    def test_transit_lost_counts_labelled_fishing_minutes_called_transit(self):
        """Labels: drift 0-40, slow 40-70, pelagic 70-100, transit 100-120. Classifier: transit 0-10, drift 10-40,
        slow 40-60, transit 60-70, gap 70-75, transit 75-80, pelagic 80-100, transit 100-120.

        By hand: lost drift 10, slow 10, pelagic 5 = 25 (the labelled transit called transit is not lost);
        labelled fishing minutes scored 40 + 30 + 30 - 5 (gap) = 95; share 25 / 95 = 0.263.
        """
        labels = [Interval(0, 40 * M, "drift-anchor"), Interval(40 * M, 70 * M, "troll-slow"),
                  Interval(70 * M, 100 * M, "troll-pelagic"), Interval(100 * M, 120 * M, "transit")]
        predictions = [Interval(0, 10 * M, "transit"), Interval(10 * M, 40 * M, "drift-anchor"),
                       Interval(40 * M, 60 * M, "troll-slow"), Interval(60 * M, 70 * M, "transit"),
                       Interval(70 * M, 75 * M, "gap"), Interval(75 * M, 80 * M, "transit"),
                       Interval(80 * M, 100 * M, "troll-pelagic"), Interval(100 * M, 120 * M, "transit")]
        lost = validate.transit_lost(confusion(labels, predictions))
        self.assertEqual(lost, {"minutes": 25, "share": 0.263,
                                "modes": {"drift-anchor": 10, "troll-slow": 10, "troll-pelagic": 5}})
        self.assertEqual(validate.transit_lost(confusion([], []))["share"], None)

    def test_a_trip_counts_under_its_dominant_labelled_mode(self):
        self.assertEqual(validate.dominant_mode([Interval(0, 40 * M, "drift-anchor"), Interval(40 * M, 70 * M, "troll-pelagic"),
                                                 Interval(70 * M, 200 * M, "transit")]), "drift-anchor")
        self.assertEqual(validate.dominant_mode([Interval(0, 30 * M, "troll-pelagic"), Interval(30 * M, 60 * M, "troll-slow")]),
                         "troll-slow", "a tie goes to the earlier mode")
        self.assertEqual(validate.dominant_mode([Interval(0, 30 * M, "transit")]), "none")


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
        table = r["confusion"]
        self.assertEqual(r["transit_lost"]["minutes"], sum(table[m]["transit"] for m in ("drift-anchor", "troll-slow", "troll-pelagic")))
        # Drift 40 labelled minutes against pelagic 30: one drift trip, from port-a, departing in October 2026 (local).
        self.assertEqual(r["coverage"], {"modes": {"drift-anchor": 1}, "ports": {"port-a": 1}, "months": {"2026-10": 1}})
        self.assertEqual(set(r["target"]["per_mode"]), {"drift-anchor", "troll-slow", "troll-pelagic"})

    def test_one_labeller_kind_and_other_thresholds(self):
        agent = validate.report(REGION, self.root, labeller="agent", now_ms=T0)
        self.assertEqual(agent["labels"], {"agent": 1})
        self.assertEqual(agent["coverage"]["modes"], {"troll-pelagic": 1})
        self.assertEqual(agent["kinds"]["drift-anchor"]["labelled_min"], 0)
        self.assertEqual(agent["minutes"]["labelled"], 30)
        override = Path(self.tmp.name) / "th.json"
        override.write_text(json.dumps({"drift": {"max_sog_kn": 0.1}}))
        th = validate._thresholds(REGION, str(override))
        self.assertEqual(th.drift_max_sog_kn, 0.1)
        self.assertEqual(th.troll_pelagic_max_sog_kn, ActivityThresholds.from_region(REGION).troll_pelagic_max_sog_kn)
        retested = validate.report(REGION, self.root, thresholds=th, now_ms=T0)
        self.assertNotEqual(retested["classifier_version"], validate.report(REGION, self.root, now_ms=T0)["classifier_version"])
        self.assertEqual(retested["kinds"]["drift-anchor"]["agree_min"], 0, "no fix drifts under 0.1 kn")

    def test_a_trip_without_a_copy_is_missing(self):
        self.copy.unlink()
        r = validate.report(REGION, self.root, now_ms=T0)
        self.assertEqual(r["trips"], {"scored": 0, "missing": 1, "ports": 0})

    def test_markdown_holds_aggregates_only(self):
        text = validate.markdown(validate.report(REGION, self.root, now_ms=T0))
        self.assertIn("Fishing precision", text)
        self.assertIn("inferred from movement", text)
        self.assertIn("never confirmed fishing", text)
        self.assertIn("Transit lost:", text)
        self.assertIn("Trips by dominant labelled mode: drift-anchor 1", text)
        self.assertIn("Per mode: drift-anchor", text)
        document = json.dumps(validate.report(REGION, self.root, now_ms=T0))
        for secret in (str(MMSI), TRIP, "admin-test", "agent:test", VESSEL):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, document)

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
        self.assertIn("label", COMMANDS)


class LabelExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.var = Path(self.tmp.name) / "var"
        self.root = self.var / "CA" / "ais"
        AisStore(self.root).write(positions=track())
        env = mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(self.var)})
        env.start()
        self.addCleanup(env.stop)

    def export(self, out="labelling/2026-10", **kw):
        return labelling.export(REGION, out, source="aisstream", root=self.root, now_ms=T0 + 8 * HOUR, **kw)

    def test_each_unlabelled_trip_gets_a_minute_summary_under_fleet_var(self):
        self.assertEqual(self.export(), {"vessels": 1, "trips": 1, "labelled": 0, "written": 1})
        path = self.root / "labelling" / "2026-10" / f"{TRIP}.json"
        self.assertTrue(path.resolve().is_relative_to(self.var.resolve()))
        doc = json.loads(path.read_text())
        self.assertEqual(doc["trip_id"], TRIP)
        self.assertEqual((doc["depart_port_id"], doc["return_port_id"], doc["status"]), ("port-a", "port-a", "closed"))
        self.assertEqual(doc["window"], {"from": doc["departed_at"], "to": doc["returned_at"]})
        self.assertEqual(doc["columns"], ["t", "sog_kn", "course_change_deg", "port_nm", "local_hour", "classifier_hint"])
        self.assertIn("do not copy", doc["hint"])
        self.assertEqual(doc["basis"], "inferred-from-movement")
        rows = doc["minutes"]
        self.assertEqual(rows[0][0], doc["departed_at"])
        self.assertEqual(len({r[0] for r in rows}), len(rows), "one row a minute")
        self.assertIsNone(rows[0][2], "no course change before the second fix")
        self.assertEqual(rows[0][4], 2, "09:39Z is 02:39 in Pacific daylight time")
        self.assertGreater(max(r[3] for r in rows), 1.0)
        self.assertLessEqual({r[5] for r in rows}, set(validate.PREDICTIONS))
        self.assertTrue({"drift-anchor", "transit"} <= {r[5] for r in rows})
        for secret in (str(MMSI), VESSEL):
            self.assertNotIn(secret, path.read_text())

    def test_trips_already_labelled_or_outside_the_window_are_left_out(self):
        validate.sync(REGION, LabelWorker([trip_row()]), self.root, now_ms=T0 + 8 * HOUR)
        self.assertEqual(self.export(), {"vessels": 1, "trips": 1, "labelled": 1, "written": 0})
        self.assertEqual(self.export(out="next", window=(T0 + HOUR, T0 + 2 * HOUR))["trips"], 0)
        self.assertFalse((self.root / "next").exists())

    def test_the_export_never_writes_outside_fleet_var_or_into_the_checkout(self):
        for out in (str(Path(self.tmp.name) / "elsewhere"), "../../../elsewhere"):
            with self.assertRaises(ValueError):
                self.export(out=out)
        self.assertFalse((Path(self.tmp.name) / "elsewhere").exists())
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(ROOT / "docs")}):
            with self.assertRaises(ValueError):
                labelling.export(REGION, str(ROOT / "docs" / "labelling"), source="aisstream", root=self.root, now_ms=T0)
        self.assertFalse((ROOT / "docs" / "labelling").exists())


class LabelImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        var = Path(self.tmp.name) / "var"
        self.root = var / "CA" / "ais"
        AisStore(self.root).write(positions=track())
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(var)}):
            labelling.export(REGION, "labelling", source="aisstream", root=self.root, now_ms=T0 + 8 * HOUR)
        self.dir = self.root / "labelling"

    def proposal(self, labels=None, labeller="agent:test", trip=TRIP):
        if labels is None:
            labels = [self.label(40, 55, "transit"), self.label(55, 95, "drift-anchor"), self.label(95, 125, "troll-pelagic")]
        return {"trip_id": trip, "labeller": labeller, "labels": labels}

    @staticmethod
    def label(start, end, kind, basis="  slow wandering track  "):
        return {"started_at": iso_utc(T0 + start * M).replace(".000Z", "Z"), "ended_at": iso_utc(T0 + end * M),
                "label": kind, "basis": basis}

    def write(self, *entries):
        path = self.dir / "proposals.json"
        path.write_text(json.dumps(list(entries)))
        return path

    def errors(self, *entries):
        worker = LabelWorker([])
        with self.assertRaises(ValueError) as caught:
            labelling.import_labels(self.write(*entries), worker)
        self.assertEqual(worker.calls, [], "nothing is posted when any entry fails")
        return str(caught.exception)

    def test_a_valid_file_is_posted_one_trip_a_request(self):
        worker = LabelWorker([])
        counts = labelling.import_labels(self.write(self.proposal()), worker)
        self.assertEqual(counts, {"trips": 1, "labels": 3, "posted": 1})
        (path, body), = worker.calls
        self.assertEqual(path, "labels")
        self.assertEqual(body["trip_id"], TRIP)
        self.assertEqual(body["labeller"], "agent:test")
        self.assertEqual(body["labels"][0], {"started_at": iso_utc(T0 + 40 * M), "ended_at": iso_utc(T0 + 55 * M),
                                             "label": "transit", "basis": "slow wandering track"})

    def test_a_dry_run_checks_and_makes_no_request(self):
        path = self.write(self.proposal())
        with mock.patch.object(labelling, "Worker", side_effect=AssertionError("no Worker on a dry run")):
            self.assertEqual(labelling.main(["import", str(path), "--dry-run"]), 0)
            self.assertEqual(labelling.import_labels(path), {"trips": 1, "labels": 3, "posted": 0})

    def test_invalid_proposals_are_refused_and_nothing_is_posted(self):
        cases = {
            "labels overlap": [self.label(40, 60, "transit"), self.label(55, 95, "drift-anchor")],
            "within the trip": [self.label(30, 55, "transit")],   # before the departure at 39 min
            "label must be one of": [self.label(55, 95, "fishing")],
            "at least one minute": [self.label(55, 55, "drift-anchor")],
            "basis is required": [self.label(55, 95, "drift-anchor", basis=" ")],
            "unknown field": [{**self.label(55, 95, "drift-anchor"), "hint": "drift-anchor"}],
            "ISO UTC": [{**self.label(55, 95, "drift-anchor"), "started_at": "2026-10-05 10:35"}],
        }
        for message, labels in cases.items():
            with self.subTest(message):
                self.assertIn(message, self.errors(self.proposal(labels)))
        for labeller in ("admin-test", "agent:", "agent:a b", None):
            self.assertIn("labeller must be agent:<name>", self.errors(self.proposal(labeller=labeller)))
        self.assertIn("no export file", self.errors(self.proposal(trip=OTHER)))
        self.assertIn("once per file", self.errors(self.proposal(), self.proposal()))
        self.assertIn("1 to 200 labels", self.errors(self.proposal(labels=[])))
        message = self.errors(self.proposal(), self.proposal(labeller="admin-test", trip=OTHER))
        self.assertTrue(message.startswith("entry 2: "), message)
        self.assertNotIn(TRIP, message)
        self.assertNotIn(OTHER, message)
        self.assertEqual(labelling.main(["import", str(self.dir / "proposals.json"), "--dry-run"]), 2)


if __name__ == "__main__":
    unittest.main()

"""Fleet refresh decisions are as of the run's saved time (RF1500-19).

Discovery runs completed after the refresh time must not supply missing historical runs, open an early
``vanished`` review or fabricate a ``returned`` change. Synthetic vessels, fixed times and a scratch region
root only; the fake sink records operations and applies nothing.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.ingest import snapshot_to_dict
from skippercast.fleet.refresh import detect, refresh
from skippercast.fleet.resolve import Snapshot

NOW = "2026-09-20T00:00:00.000Z"  # 50 days after LAST_SEEN: the 45-day threshold is met
LAST_SEEN = "2026-08-01T00:00:00.000Z"
EARLIER = "2026-08-21T00:00:00.000Z"
LATER = ["2026-10-05T00:00:00.000Z", "2026-10-20T00:00:00.000Z", "2026-11-01T00:00:00.000Z"]
VID = "a" * 32
RULES = {"vanished_runs": 3, "vanished_days": 45}


def vessel(status="active", last_seen=LAST_SEEN, **extra):
    return {"id": VID, "slug": "sea-example", "name": "Sea Example", "status": status, "port_id": "morro-bay",
            "landing_id": None, "operator_id": None, "mmsi": None, "vessel_class": None,
            "last_seen_at": last_seen, "offerings": [], **extra}


def run(history, *, now=NOW, complete=True, sent=(), vessels=None):
    return detect(Snapshot(vessels if vessels is not None else [vessel()]), list(sent), now, complete=complete,
                  history=history, **RULES)


def kinds(out):
    return [op["kind"] for op in out if op["op"] == "change.record"]


def listed():
    return [{"op": "vessel.upsert", "id": VID, "slug": "sea-example", "name": "Sea Example"}]


class DetectAsOfTests(unittest.TestCase):
    def test_future_runs_cannot_complete_vanished_threshold(self):
        # one genuine earlier miss + the complete current run = 2 < 3, however many later runs exist
        self.assertEqual(run([EARLIER, *LATER]), [])
        self.assertEqual(run([EARLIER]), [])

    def test_future_only_history_cannot_mark_returned(self):
        self.assertEqual(kinds(run(LATER, sent=listed())), [])
        control = run(["2026-08-10T00:00:00.000Z", "2026-08-20T00:00:00.000Z", "2026-09-01T00:00:00.000Z", *LATER],
                      sent=listed())
        self.assertEqual(kinds(control), ["returned"])
        self.assertEqual(control[0]["after_json"], {"listed_at": NOW})

    def test_equal_now_is_not_earlier(self):
        # only EARLIER counts: 1 + the current run = 2 < 3 unless an excluded entry is wrongly counted
        excluded = ["2026-09-20T00:00:00.000Z", "2026-09-20T00:00:00Z", "2026-09-20T00:00:00.0Z",
                    "2026-09-20T00:00:00.000000Z", "2026-09-21T00:00:00.000Z", "2026-07-01T00:00:00.000Z",
                    LAST_SEEN, "2026-08-01T00:00:00Z"]
        for now in (NOW, "2026-09-20T00:00:00Z", "2026-09-20T00:00:00.00Z"):
            with self.subTest(now=now):
                self.assertEqual(run([EARLIER, *excluded], now=now), [])
                self.assertEqual(kinds(run([EARLIER, *excluded], now=now, sent=listed())), [])

    def test_earlier_runs_still_cross_threshold(self):
        two = ["2026-08-10T00:00:00.000Z", EARLIER]
        out = run([*two, *LATER])
        self.assertEqual([op["op"] for op in out], ["review.open", "change.record"])
        review, change = out
        self.assertEqual(review["fingerprint"], f"{VID}|{LAST_SEEN}")
        self.assertEqual((review["subject_id"], review["opened_at"], review["candidate_json"]),
                         (VID, NOW, {"last_seen_at": LAST_SEEN}))
        self.assertEqual((change["kind"], change["detected_at"], change["review_id"] is not None),
                         ("vanished", NOW, True))
        self.assertEqual(out, run(two))
        self.assertEqual(run(two[1:]), [])  # one earlier miss does not
        # the output keeps the caller's spelling of now
        self.assertEqual(run(two, now="2026-09-20T00:00:00Z")[0]["opened_at"], "2026-09-20T00:00:00Z")

    def test_partial_current_run_stays_nonvanishing(self):
        history = ["2026-08-05T00:00:00.000Z", "2026-08-10T00:00:00.000Z", EARLIER, "2026-09-10T00:00:00.000Z"]
        self.assertEqual(run(history, complete=False), [])
        self.assertEqual(run([*history, *LATER], complete=False), [])

    def test_nonhistory_changes_are_identical(self):
        old = vessel(last_seen="2026-09-10T00:00:00.000Z", operator_id="op-old", mmsi="999000001",
                     offerings=[{"id": "b" * 32, "name": "Half Day", "trip_type": "half-day", "status": "active",
                                 "price_cents": 9500, "departs_local": "06:30", "days": ["sat"]}])
        sent = [{"op": "vessel.upsert", "id": VID, "slug": "sea-example", "name": "Sea Example",
                 "operator_id": "op-new", "mmsi": "999000002", "port_id": "port-san-luis"},
                {"op": "offering.upsert", "id": "b" * 32, "vessel_id": VID, "name": "Half Day",
                 "price_cents": 10500, "departs_local": "07:30", "days_json": ["sun"]}]
        base = run([EARLIER], sent=sent, vessels=[old])
        self.assertEqual(set(kinds(base)), {"sold", "mmsi", "moved", "price", "schedule"})
        self.assertEqual(run([EARLIER, *LATER], sent=sent, vessels=[old]), base)


class FakeSink:
    def __init__(self):
        self.applied = []

    def apply(self, ops):
        self.applied.append(list(ops))
        return {"changed": len(ops)}


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


class RefreshReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.region = SimpleNamespace(thresholds={"refresh": {"vanished_after_runs": 3, "vanished_after_days": 45}})
        current = self.root / "runs" / "r-current"
        write(current / "ingest-snapshot.json", {"now": NOW, "snapshot": snapshot_to_dict(Snapshot([vessel()]))})
        write(current / "discover.json", {"complete": True, "at": NOW})
        (current / "ingest-ops.jsonl").write_text("", encoding="utf-8")
        self.discover("r-aug", EARLIER)
        self.ctx = RunContext(self.region, None, current, lambda: NOW)

    def discover(self, name, at, complete=True):
        write(self.root / "runs" / name / "discover.json", {"complete": complete, "at": at})

    def test_saved_refresh_replay_ignores_later_directories(self):
        sink = FakeSink()
        first = refresh(self.ctx, sink)
        self.assertEqual((first["vanished_reviews"], first["changes"], first["complete"]), (0, 0, 1))
        for n, at in enumerate(LATER):
            self.discover(f"r-later-{n}", at)
        self.discover("r-later-partial", "2026-11-02T00:00:00.000Z", complete=False)
        again = refresh(self.ctx, sink)
        self.assertEqual(again, first)
        self.assertEqual(sink.applied, [])

    def test_earlier_directories_still_open_the_review(self):
        self.discover("r-aug-2", "2026-08-10T00:00:00.000Z")
        for n, at in enumerate(LATER):
            self.discover(f"r-later-{n}", at)
        sink = FakeSink()
        result = refresh(self.ctx, sink)
        self.assertEqual((result["vanished_reviews"], result["kinds"]), (1, {"vanished": 1}))
        self.assertEqual([op["op"] for op in sink.applied[0]], ["review.open", "change.record"])
        # two earlier directories + the complete current run = 3 runs
        self.assertEqual(sink.applied[0][0]["opened_at"], NOW)


if __name__ == "__main__":
    unittest.main()

"""F07-01 / F08-01: a replace-window must not span a day the source archive did not deliver (offline fixture).

Missing observations are not evidence that no trip happened. ``gap_violations`` is the detector: given what
``backfill`` reported (``missing`` / ``failed`` days) and the replace windows it sent to the Worker, it names every
undelivered UTC day a destructive window covers. The controls:

* valid positive: every day delivered, trip present -> no violation;
* valid empty: every day delivered but genuinely empty -> a replace window is representable and is not a violation;
* affected: one day unpublished (404) or corrupt, prior history in the window -> the detector names that day if a
  window covering it was sent, and the prior trip survives exactly when none was.

The live-path tests state the invariant (history is lost only if a window crossed the gap), not which side the
current code is on, so they stay green when the guard lands. The detector itself is proven on synthetic bodies.
Everything is synthetic; no Worker, network or real data.
"""
from datetime import datetime, timedelta, timezone

from skippercast.fleet.ais import backfill as bf
from skippercast.fleet.ais.sources.marinecadastre import MarineCadastreSource
from skippercast.http import FakeSession
from tests.unit.test_fleet_backfill import (DAY, NEXT, REGION, T0, BackfillTestCase, day_file, day_url, session, zst)
from tests.unit.test_fleet_process import FakeWorker

UTC = timezone.utc
NOW = T0 + 200 * 86_400_000


def _iso_day(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).date()


def gap_violations(counts, replace_windows):
    """UTC days (ISO) that the backfill did not deliver yet some sent replace window ``[from, to)`` covers."""
    undelivered = set(counts["missing"]) | {f["day"] for f in counts["failed"]}
    hit = set()
    for w in replace_windows:
        start = _iso_day(w["from"])
        last = (datetime.fromisoformat(w["to"].replace("Z", "+00:00")) - timedelta(milliseconds=1)).astimezone(UTC).date()
        hit |= {d for d in undelivered if start <= datetime.fromisoformat(d).date() <= last}
    return sorted(hit)


def replace_windows(worker):
    return [w for body in worker.posts("activity", "replace") for w in body["replace"]]


class DetectorTests(BackfillTestCase):
    WINDOW = {"mmsi": "999000001", "from": "2026-06-20T07:00:00Z", "to": "2026-06-21T07:00:00Z"}

    def test_detector_flags_a_window_over_an_undelivered_day(self):
        counts = {"missing": ["2026-06-21"], "failed": []}
        self.assertEqual(gap_violations(counts, [self.WINDOW]), ["2026-06-21"])
        counts = {"missing": [], "failed": [{"day": "2026-06-20", "error": "corrupt"}]}
        self.assertEqual(gap_violations(counts, [self.WINDOW]), ["2026-06-20"])

    def test_detector_passes_complete_coverage_and_a_window_clear_of_the_gap(self):
        self.assertEqual(gap_violations({"missing": [], "failed": []}, [self.WINDOW]), [])
        self.assertEqual(gap_violations({"missing": ["2026-06-22"], "failed": []}, [self.WINDOW]), [])
        self.assertEqual(gap_violations({"missing": ["2026-06-21"], "failed": []}, []), [], "no window sent")


class CoverageControlTests(BackfillTestCase):
    def seeded(self):
        """A worker already holding one earlier trip inside the requested departure window."""
        worker = FakeWorker()
        worker.stored = {"trip-prior": {"id": "trip-prior", "mmsi": "999000123", "source": bf.SOURCE_ID,
                                        "departed_at": "2026-06-20T17:00:00Z"}}
        return worker

    def backfill_with(self, routes, worker=None):
        worker = worker or self.seeded()
        source = MarineCadastreSource(session=routes, workdir=self.store.root / "staging")
        counts = bf.backfill(REGION, worker, first=DAY, last=DAY, root=self.root, source=source, now_ms=NOW)
        return worker, counts

    def assert_history_follows_coverage(self, worker, counts):
        violations = gap_violations(counts, replace_windows(worker))
        self.assertEqual("trip-prior" in worker.stored, not violations,
                         "prior history may be replaced only by a window with no undelivered day")
        return violations

    def test_valid_control_complete_input_has_no_violation(self):
        worker = self.seeded()
        # the prior trip's id is not the derived one, so the window replaces it with the freshly derived trip
        worker, counts = self.backfill_with(session(), worker)
        self.assertEqual((counts["missing"], counts["failed"]), ([], []))
        self.assertTrue(replace_windows(worker))
        self.assertEqual(gap_violations(counts, replace_windows(worker)), [])
        self.assertNotIn("trip-prior", worker.stored)
        self.assertEqual(len(worker.stored), 1)

    def test_complete_empty_interval_may_replace_its_window(self):
        worker, counts = self.backfill_with(FakeSession({day_url(DAY): zst([]), day_url(NEXT): zst([])}))
        self.assertEqual((counts["missing"], counts["failed"]), ([], []))
        self.assertTrue(replace_windows(worker), "a certified-complete empty interval stays representable")
        self.assertEqual(gap_violations(counts, replace_windows(worker)), [])

    def test_affected_control_unpublished_day_with_prior_history(self):
        worker, counts = self.backfill_with(FakeSession({day_url(DAY): day_file(), day_url(NEXT): (404, b"")}))
        self.assertEqual(counts["missing"], ["2026-06-21"])
        violations = self.assert_history_follows_coverage(worker, counts)
        self.assertTrue(set(violations) <= {"2026-06-21"})

    def test_affected_control_corrupt_day_with_prior_history(self):
        whole = day_file()
        worker, counts = self.backfill_with(FakeSession({day_url(DAY): whole[:len(whole) // 2], day_url(NEXT): zst([])}))
        self.assertEqual([f["day"] for f in counts["failed"]], ["2026-06-20"])
        violations = self.assert_history_follows_coverage(worker, counts)
        self.assertTrue(set(violations) <= {"2026-06-20"})

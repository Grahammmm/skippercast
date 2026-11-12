"""RF0540-9: recent-history samples follow the half-open [start, end) coverage window."""

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from skippercast.pipeline import ndbc_history as nh

HEADER = "#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE\n"
HOURLY = timedelta(hours=1)


def rows(times):
    return HEADER + "".join(
        f"{t:%Y %m %d %H %M} 300  6.0  8.0   1.8    11   7.5 290 1014.0  14.0  15.0    MM   MM   MM    MM\n" for t in times)


def summary(times, now, days=1):
    observations, qc = nh.parse(rows(times), now)
    return nh.recent_summary(observations, qc, now, days)


class WindowBoundaryTests(TestCase):
    NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)

    def test_exact_hour_full_window_never_exceeds_one(self):
        for days in (1, 45):
            start = self.NOW - timedelta(days=days)
            times = [start + HOURLY * i for i in range(days * 24 + 1)]  # includes the cutoff
            recent = summary(times, self.NOW, days)
            self.assertEqual((recent["expectedHours"], recent["observedHours"]), (days * 24, days * 24))
            self.assertEqual((recent["hourCoverageFraction"], recent["maxGapHours"]), (1.0, 0))
            self.assertNotIn("2026-10-07T12:00:00.000Z", [h["at"] for h in recent["hours"]])
            self.assertEqual(recent["lastObservedAt"], "2026-10-07T11:00:00.000Z")

    def test_start_included_end_excluded_at_millisecond_precision(self):
        start = self.NOW - timedelta(days=1)
        recent = summary([start - timedelta(minutes=1), start, self.NOW - timedelta(minutes=1), self.NOW,
                          self.NOW + timedelta(minutes=1)], self.NOW + timedelta(minutes=2))
        # cutoff is 12:02: start is 12:00 yesterday; every sample is inside except the one before start
        self.assertEqual(recent["firstObservedAt"], "2026-10-06T12:00:00.000Z")
        recent = summary([start - timedelta(minutes=1), start, self.NOW - timedelta(minutes=1), self.NOW], self.NOW)
        self.assertEqual((recent["firstObservedAt"], recent["lastObservedAt"]),
                         ("2026-10-06T12:00:00.000Z", "2026-10-07T11:59:00.000Z"))
        self.assertEqual(recent["hours"][-1]["at"], "2026-10-07T11:00:00.000Z")
        self.assertEqual(recent["hours"][-1]["counts"]["waveFt"], 1)

    def test_partial_hour_keeps_current_bucket(self):
        now = self.NOW + timedelta(minutes=30)
        recent = summary([self.NOW - HOURLY, self.NOW, now], now)
        self.assertEqual(recent["expectedHours"], 25)
        self.assertEqual(recent["hours"][-1]["at"], "2026-10-07T12:00:00.000Z")
        self.assertEqual(recent["lastObservedAt"], "2026-10-07T12:00:00.000Z")
        self.assertEqual(recent["hours"][-1]["sampleCount"], 1)

    def test_boundary_only_observation_is_unavailable(self):
        recent = summary([self.NOW], self.NOW)
        self.assertEqual((recent["observedHours"], recent["hours"], recent["firstObservedAt"], recent["lastObservedAt"]),
                         (0, [], None, None))
        self.assertEqual((recent["stale"], recent["hourCoverageFraction"], recent["maxGapHours"]), (True, 0.0, 24))

    def test_interior_samples_unchanged(self):
        recent = summary([self.NOW - 2 * HOURLY, self.NOW - timedelta(minutes=30)], self.NOW)
        self.assertEqual((recent["expectedHours"], recent["observedHours"], recent["stale"]), (24, 2, False))
        self.assertEqual(recent["lastObservedAt"], "2026-10-07T11:30:00.000Z")

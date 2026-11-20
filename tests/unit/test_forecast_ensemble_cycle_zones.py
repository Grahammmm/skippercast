"""GEFS latest_cycle picks the same UTC cycle and URLs for equivalent zoned clocks."""
from datetime import datetime, timedelta, timezone
import unittest

from skippercast.forecast import ensemble

OFFSETS = (timezone.utc, timezone(timedelta(hours=5, minutes=30)), timezone(timedelta(hours=-7)),
           timezone(timedelta(hours=-3, minutes=-30)))


def run(now, available=(), lookback=48):
    seen = []
    published = {ensemble.gefs_url(c, m, ensemble.STEPS[-1]) + '.idx'
                 for c in available for m in (0, ensemble.MEMBERS - 1)}

    def exists(url):
        seen.append(url)
        return url in published
    return ensemble.latest_cycle(now, lookback_hours=lookback, exists=exists), seen


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class CycleZoneTests(unittest.TestCase):
    def assert_same_everywhere(self, instant, available, expected, lookback=48):
        control = run(instant, available, lookback)
        self.assertEqual(control[0], expected)
        for zone in OFFSETS:
            got = run(instant.astimezone(zone), available, lookback)
            self.assertEqual(got, control, zone)
            if expected:
                self.assertEqual(got[0].utcoffset(), timedelta(0))

    def test_equivalent_aware_clocks_choose_same_cycle_and_urls(self):
        six = utc(2026, 9, 27, 6)
        self.assert_same_everywhere(utc(2026, 9, 27, 9, 30), [six], six)
        self.assertEqual(run(utc(2026, 9, 27, 9, 30), [six])[1][0].split('/')[3:5], ['gefs.20260927', '06'])

    def test_zoned_calendar_rollover_uses_utc_bucket_date(self):
        expected = utc(2026, 9, 27, 18)
        self.assert_same_everywhere(utc(2026, 9, 28, 1, 15), [expected], expected)
        self.assert_same_everywhere(utc(2026, 9, 28, 0, 10), [utc(2026, 9, 27, 18)], expected)
        midnight = utc(2026, 9, 28, 0)
        self.assert_same_everywhere(utc(2026, 9, 28, 3, 45), [midnight], midnight)

    def test_delay_threshold_and_lookback_remain_unchanged(self):
        six, zero = utc(2026, 9, 27, 6), utc(2026, 9, 27, 0)
        both = [six, zero]
        self.assert_same_everywhere(utc(2026, 9, 27, 8, 29, 59), both, zero)
        self.assert_same_everywhere(utc(2026, 9, 27, 8, 30), both, six)
        self.assert_same_everywhere(utc(2026, 9, 27, 8, 30, 1), both, six)
        self.assert_same_everywhere(utc(2026, 9, 27, 9, 30), [], None, lookback=3)

    def test_incomplete_control_or_last_member_falls_back(self):
        now, older, newer = utc(2026, 9, 27, 9, 30), utc(2026, 9, 27, 0), utc(2026, 9, 27, 6)
        self.assert_same_everywhere(now, [older], older)
        final = ensemble.STEPS[-1]
        for member in (0, ensemble.MEMBERS - 1):
            for zone in OFFSETS:
                seen = []
                partial = {ensemble.gefs_url(newer, member, final) + '.idx',
                           ensemble.gefs_url(older, 0, final) + '.idx',
                           ensemble.gefs_url(older, ensemble.MEMBERS - 1, final) + '.idx'}

                def exists(url):
                    seen.append(url)
                    return url in partial
                self.assertEqual(ensemble.latest_cycle(now.astimezone(zone), exists=exists), older)
                self.assertIn('gefs.20260927/00/', seen[-1])


if __name__ == '__main__':
    unittest.main()

"""scripts/ops_report.py: a fleet push dated after the report time never reports a numeric heartbeat age."""
import unittest
from datetime import datetime, timezone

from scripts import ops_report

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
UNKNOWN = 'listener heartbeat age unknown'


def line(pushed_at, beat='0', issue='', messages='5'):
    row = {'pushed_at': pushed_at, 'heartbeat_age_s': beat, 'messages_24h': messages}
    return ops_report.fleet_line([row], issue, NOW)


class FuturePushTests(unittest.TestCase):
    def test_future_push_has_unknown_age(self):
        for pushed in ('2026-10-05 10:00:01', '2026-10-06 10:00:00'):
            for beat in ('0', '600'):
                self.assertEqual(line(pushed, beat), f'Fleet AIS: {UNKNOWN}; 5 AIS rows stored in 24 h; no open fleet-ais-stale issue.')
        self.assertIn(f'{UNKNOWN}; 5 AIS rows stored in 24 h; open fleet-ais-stale issue #4.', line('2026-10-06 10:00:00', issue='#4'))
        self.assertIn(f'{UNKNOWN}; 5 AIS rows stored in 24 h; fleet-ais-stale issue unknown.', line('2026-10-06 10:00:00', issue=None))

    def test_future_microsecond_and_exact_now_boundary(self):
        self.assertIn(UNKNOWN, line('2026-10-05T10:00:00.000001'))
        self.assertIn('listener heartbeat 0.0 h old', line('2026-10-05 10:00:00'))
        self.assertIn('listener heartbeat 0.5 h old', line('2026-10-05 10:00:00', beat='1800'))

    def test_offset_instants_not_wall_clock_control(self):
        # 11:30+02:00 is 09:30 UTC: a past instant despite the later wall clock.
        self.assertIn('listener heartbeat 0.5 h old', line('2026-10-05T11:30:00+02:00'))
        same = {line(t) for t in ('2026-10-05T09:30:00Z', '2026-10-05 09:30:00', '2026-10-05T11:30:00+02:00')}
        self.assertEqual(len(same), 1)
        self.assertIn(UNKNOWN, line('2026-10-05T12:30:00+02:00'))

    def test_past_push_preserves_elapsed_plus_heartbeat(self):
        self.assertIn('listener heartbeat 1.5 h old', line('2026-10-05 09:00:00', beat='1800'))
        future = {'fleet_ais': [{'pushed_at': '2026-10-06 10:00:00', 'heartbeat_age_s': '0', 'messages_24h': '5'}]}
        text = ops_report.report(dict(future, routes=[]), '', NOW)
        self.assertIn(f'Fleet AIS: {UNKNOWN}; 5 AIS rows stored in 24 h; no open fleet-ais-stale issue.', text)

    def test_unparseable_and_absent_controls_unchanged(self):
        for pushed in ('not a date', None, ''):
            self.assertIn(UNKNOWN, line(pushed))
        self.assertIsNone(ops_report.fleet_line([], '', NOW))
        self.assertEqual(ops_report.fleet_line([], '#7', NOW), 'Fleet AIS: no processor heartbeat in 24 h; open fleet-ais-stale issue #7.')


if __name__ == '__main__':
    unittest.main()

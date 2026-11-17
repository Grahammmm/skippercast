"""latest_cycle picks UTC cycles and provider URLs for equivalent aware clocks."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from skippercast.forecast import fetch
from skippercast.forecast.models import ECMWF_AWS, ECMWF_PORTAL, MODELS

ECMWF = MODELS['ecmwf_ifs025']
GFS = next(model for model in MODELS.values() if model.family == 'gfs')
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
PDT = timezone(timedelta(hours=-7))
NEG_HALF = timezone(timedelta(hours=-3, minutes=-30))


def run(model, now, answers=None, **kw):
    """Return (cycle, ordered exists() URL trace); URLs absent from `answers` count as published
    when answers is None, else as missing; an exception value is raised."""
    calls = []

    def exists(url):
        calls.append(url)
        if answers is None:
            return True
        answer = answers.get(url, False)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    with mock.patch.object(fetch, 'exists', exists):
        return fetch.latest_cycle(model, now, **kw), calls


def url(model, y, m, d, h, base=None):
    cycle = datetime(y, m, d, h, tzinfo=UTC)
    args = (model, cycle, model.steps[-1]) + ((base,) if base else ())
    return fetch.index_url(*args)


class ForecastCycleZones(unittest.TestCase):
    def test_equivalent_clocks_select_same_utc_cycle_and_urls(self):
        instant = datetime(2026, 9, 27, 9, 30, tzinfo=UTC)
        want = [(GFS, (datetime(2026, 9, 27, 6, tzinfo=UTC), [url(GFS, 2026, 9, 27, 6)])),
                (ECMWF, (datetime(2026, 9, 27, 0, tzinfo=UTC), [url(ECMWF, 2026, 9, 27, 0, ECMWF_AWS)]))]
        for model, expected in want:
            for clock in (instant, instant.astimezone(IST), instant.astimezone(PDT)):
                cycle, calls = run(model, clock)
                self.assertEqual((cycle, calls), expected, clock.isoformat())
                self.assertEqual(cycle.utcoffset(), timedelta(0))

    def test_offset_rollover_uses_utc_provider_date(self):
        instant = datetime(2026, 9, 28, 1, 30, tzinfo=UTC)
        for clock in (instant, instant.astimezone(PDT), instant.astimezone(NEG_HALF), instant.astimezone(IST)):
            cycle, calls = run(GFS, clock)
            self.assertEqual(cycle, datetime(2026, 9, 27, 18, tzinfo=UTC), clock.isoformat())
            self.assertEqual(calls, [url(GFS, 2026, 9, 27, 18)])
            self.assertIn('gfs.20260927/18/', calls[0])

    def test_delay_and_inclusive_lookback_are_unchanged(self):
        at = datetime(2026, 9, 27, 8, 30, tzinfo=UTC)
        self.assertEqual(run(GFS, at)[0], datetime(2026, 9, 27, 6, tzinfo=UTC))
        self.assertEqual(run(GFS, at - timedelta(minutes=1))[0], datetime(2026, 9, 27, 0, tzinfo=UTC))
        self.assertEqual(run(GFS, (at - timedelta(minutes=1)).astimezone(IST))[0], datetime(2026, 9, 27, 0, tzinfo=UTC))
        only_00 = {url(GFS, 2026, 9, 27, 0): True}
        self.assertIsNone(run(GFS, at, answers=only_00, lookback_hours=7)[0])
        self.assertEqual(run(GFS, at, answers=only_00, lookback_hours=8)[0], datetime(2026, 9, 27, 0, tzinfo=UTC))

    def test_mirror_fallback_and_gfs_errors_are_preserved(self):
        clock = datetime(2026, 9, 27, 9, 30, tzinfo=UTC).astimezone(IST)
        aws, portal = url(ECMWF, 2026, 9, 27, 0, ECMWF_AWS), url(ECMWF, 2026, 9, 27, 0, ECMWF_PORTAL)
        cycle, calls = run(ECMWF, clock, answers={aws: OSError('down'), portal: True})
        self.assertEqual((cycle, calls), (datetime(2026, 9, 27, 0, tzinfo=UTC), [aws, portal]))
        self.assertEqual(run(ECMWF, clock, answers={aws: True})[1], [aws])
        with self.assertRaises(OSError):
            run(GFS, clock, answers={url(GFS, 2026, 9, 27, 6): OSError('x')})


if __name__ == '__main__':
    unittest.main()

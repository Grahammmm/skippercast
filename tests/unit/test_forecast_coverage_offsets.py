"""Only a real numeric zero utc_offset_seconds admits a forecast row as UTC."""
import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from skippercast.pipeline.forecast_coverage import audit_forecast_coverage

NOW = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
REGION = {'timezone': 'America/Los_Angeles', 'forecast_points': [{'id': 'inner'}, {'id': 'outer'}]}
WIND, WAVE = ('gfs_global', 'ecmwf_ifs025'), ('ncep_gfswave016', 'ecmwf_wam')
DATES = [(NOW.astimezone(ZoneInfo(REGION['timezone'])).date() + timedelta(days=d)).isoformat() for d in range(1, 8)]


def _forecast():
    zone = ZoneInfo(REGION['timezone'])
    day = NOW.astimezone(zone).date()
    times = [int(datetime((day + timedelta(days=d)).year, (day + timedelta(days=d)).month,
                          (day + timedelta(days=d)).day, hour, tzinfo=zone).timestamp())
             for d in range(1, 8) for hour in range(7, 14)]
    models = {}
    for name in WIND + WAVE:
        field, unit = ('wind_speed_10m', 'kn') if name in WIND else ('wave_height', 'ft')
        models[name] = {
            'meta': {'last_run_initialisation_time': NOW.timestamp() - 3600, 'data_end_time': times[-1]},
            'data': [{'utc_offset_seconds': 0,
                      'hourly_units': {'time': 'unixtime', field: unit, 'wave_period': 's'},
                      'hourly': {'time': list(times), field: [5.0] * len(times),
                                 'wave_period': [9.0] * len(times)}} for _ in range(2)]}
    return {'models': models}


def _days(rated, compared, status):
    return [{'date': date, 'rated_hours': rated, 'two_model_hours': compared, 'status': status}
            for date in DATES]


def _summary(rated, two, incomplete, unavailable):
    return {'point_days': 14, 'rated_point_days': rated, 'two_model_point_days': two,
            'incomplete_point_days': incomplete, 'unavailable_point_days': unavailable}


COMPLETE = _days(7, 7, 'complete')


class ForecastCoverageOffsetTests(unittest.TestCase):
    def _audit(self, offsets):
        forecast = _forecast()
        for (name, point), offset in offsets.items():
            forecast['models'][name]['data'][point]['utc_offset_seconds'] = offset
        forecast = json.loads(json.dumps(forecast))
        before = copy.deepcopy(forecast)
        result = audit_forecast_coverage(forecast, REGION, NOW)
        self.assertEqual(forecast, before)
        return result

    def test_valid_numeric_zero_result_matches_independent_expectation(self):
        expected = {'window': '7 a.m.–1 p.m. local, next seven dates',
                    'points': [{'point_id': 'inner', 'days': COMPLETE},
                               {'point_id': 'outer', 'days': COMPLETE}],
                    'summary': _summary(14, 14, 0, 0)}
        self.assertEqual(self._audit({}), expected)

    def test_json_false_offset_cannot_certify_wave_coverage(self):
        result = self._audit({(name, point): False for name in WAVE for point in (0, 1)})
        self.assertEqual(result['summary'], _summary(0, 0, 14, 14))
        for point in result['points']:
            self.assertEqual(point['days'], _days(0, 0, 'unavailable'))

    def test_one_bad_model_preserves_alternative_rating(self):
        for name in (WIND[0], WAVE[1]):
            with self.subTest(model=name):
                result = self._audit({(name, 0): False})
                self.assertEqual(result['summary'], _summary(14, 7, 0, 0))
                self.assertEqual(result['points'][0]['days'], _days(7, 0, 'limited'))
                self.assertEqual(result['points'][1]['days'], COMPLETE)

    def test_two_bad_models_are_point_local(self):
        for family in (WIND, WAVE):
            with self.subTest(family=family):
                result = self._audit({(name, 0): False for name in family})
                self.assertEqual(result['summary'], _summary(7, 7, 7, 7))
                self.assertEqual(result['points'][0]['days'], _days(0, 0, 'unavailable'))
                self.assertEqual(result['points'][1]['days'], COMPLETE)

    def test_only_real_numeric_zero_is_utc(self):
        for offset in (0, 0.0, -0.0):
            with self.subTest(good=offset):
                result = self._audit({(name, p): offset for name in WAVE for p in (0, 1)})
                self.assertEqual(result['summary'], _summary(14, 14, 0, 0))
        bad = (False, True, None, '0', '', [], [0], {}, {'a': 0}, float('nan'),
               float('inf'), float('-inf'), 10 ** 400, 3600, -3600, 0.5)
        for index, offset in enumerate(bad):
            with self.subTest(bad=index):
                forecast = _forecast()
                for name in WAVE:
                    forecast['models'][name]['data'][0]['utc_offset_seconds'] = offset
                result = audit_forecast_coverage(forecast, REGION, NOW)
                self.assertEqual(result['summary'], _summary(7, 7, 7, 7))
                self.assertEqual(result['points'][0]['days'], _days(0, 0, 'unavailable'))
        forecast = _forecast()
        for name in WAVE:
            del forecast['models'][name]['data'][0]['utc_offset_seconds']
        self.assertEqual(audit_forecast_coverage(forecast, REGION, NOW)['summary'],
                         _summary(7, 7, 7, 7))


if __name__ == '__main__':
    unittest.main()

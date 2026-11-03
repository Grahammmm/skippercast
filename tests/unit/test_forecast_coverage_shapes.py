"""Only real numbers from well-formed model blocks count as rated forecast hours."""
from datetime import datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from skippercast.pipeline.forecast_coverage import audit_forecast_coverage

WIND, WAVE = ('gfs_global', 'ecmwf_ifs025'), ('ncep_gfswave016', 'ecmwf_wam')


class ForecastCoverageShapeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
        self.region = {'timezone': 'America/Los_Angeles',
                       'forecast_points': [{'id': 'inner'}, {'id': 'outer'}]}
        zone = ZoneInfo(self.region['timezone'])
        day = self.now.astimezone(zone).date()
        self.dates = [(day + timedelta(days=d)).isoformat() for d in range(1, 8)]
        times = [int(datetime((day+timedelta(days=d)).year,
                              (day+timedelta(days=d)).month,
                              (day+timedelta(days=d)).day, hour, tzinfo=zone).timestamp())
                 for d in range(1, 8) for hour in range(7, 14)]
        self.forecast = {'models': {}}
        for model in WIND + WAVE:
            field, unit = ('wind_speed_10m', 'kn') if model in WIND else ('wave_height', 'ft')
            self.forecast['models'][model] = {
                'meta': {'last_run_initialisation_time': self.now.timestamp()-3600,
                         'data_end_time': times[-1]},
                'data': [{'utc_offset_seconds': 0,
                          'hourly_units': {'time': 'unixtime', field: unit, 'wave_period': 's'},
                          'hourly': {'time': times, field: [5.0]*len(times),
                                     'wave_period': [9.0]*len(times)}} for _ in range(2)]}

    def model(self, name):
        return self.forecast['models'][name]

    def audit(self, forecast=None):
        return audit_forecast_coverage(self.forecast if forecast is None else forecast, self.region, self.now)

    def first_day(self, result, point=0):
        return result['points'][point]['days'][0]

    def test_complete_fixture_matches_main_result(self):
        day = {'rated_hours': 7, 'two_model_hours': 7, 'status': 'complete'}
        expected = {'window': '7 a.m.–1 p.m. local, next seven dates',
                    'points': [{'point_id': pid, 'days': [dict(date=d, **day) for d in self.dates]}
                               for pid in ('inner', 'outer')],
                    'summary': {'point_days': 14, 'rated_point_days': 14, 'two_model_point_days': 14,
                                'incomplete_point_days': 0, 'unavailable_point_days': 0}}
        self.assertEqual(self.audit(), expected)

    def test_bool_wind_is_rated_only_when_other_wind_model_has_a_number(self):
        self.model('gfs_global')['data'][0]['hourly']['wind_speed_10m'][0] = True
        result = self.audit()
        self.assertEqual(self.first_day(result)['rated_hours'], 7)
        self.assertEqual(self.first_day(result)['two_model_hours'], 6)
        self.model('ecmwf_ifs025')['data'][0]['hourly']['wind_speed_10m'][0] = False
        result = self.audit()
        self.assertEqual(self.first_day(result)['rated_hours'], 6)
        self.assertEqual(self.first_day(result)['status'], 'limited')
        self.assertEqual(result['summary']['two_model_point_days'], 13)
        self.assertEqual(self.first_day(result, 1)['rated_hours'], 7)

    def test_bool_wave_period_is_no_sample(self):
        self.model('ecmwf_wam')['data'][0]['hourly']['wave_period'][0] = True
        result = self.audit()
        self.assertEqual(self.first_day(result)['two_model_hours'], 6)
        self.model('ncep_gfswave016')['data'][0]['hourly']['wave_period'][0] = True
        self.assertEqual(self.first_day(self.audit())['rated_hours'], 6)

    def test_nan_inf_and_future_run_times_contribute_nothing(self):
        now = self.now.timestamp()
        for bad in (float('nan'), float('inf'), now + 2 * 3600, True):
            with self.subTest(run=bad):
                self.model('ecmwf_ifs025')['meta']['last_run_initialisation_time'] = bad
                result = self.audit()
                self.assertEqual(result['summary']['two_model_point_days'], 0)
                self.assertEqual(result['summary']['rated_point_days'], 14)
        self.model('ecmwf_ifs025')['meta']['last_run_initialisation_time'] = now + 30 * 60
        self.assertEqual(self.audit()['summary']['two_model_point_days'], 14)

    def test_nan_data_end_time_is_no_sample_and_absent_is_unchanged(self):
        for bad in (float('nan'), float('inf'), '2026-10-03'):
            with self.subTest(end=bad):
                for name in WAVE:
                    self.model(name)['meta']['data_end_time'] = bad
                self.assertEqual(self.audit()['summary']['unavailable_point_days'], 14)
        for name in WAVE:
            del self.model(name)['meta']['data_end_time']
        self.assertEqual(self.audit()['summary']['two_model_point_days'], 14)

    def test_non_object_model_row_and_hourly_blocks_are_not_rated(self):
        cases = [lambda: self.forecast['models'].__setitem__('gfs_global', []),
                 lambda: self.forecast['models'].__setitem__('gfs_global', ['x']),
                 lambda: self.model('gfs_global').__setitem__('data', ['x', 'y']),
                 lambda: self.model('gfs_global').__setitem__('data', {'0': {}}),
                 lambda: self.model('gfs_global').__setitem__('meta', ['x']),
                 lambda: self.model('gfs_global')['data'][0].__setitem__('hourly', []),
                 lambda: self.model('gfs_global')['data'][0].__setitem__('hourly', 'x'),
                 lambda: self.model('gfs_global')['data'][0].__setitem__('hourly_units', ['x'])]
        for index, damage in enumerate(cases):
            with self.subTest(case=index):
                self.setUp()
                damage()
                result = self.audit()
                self.assertEqual(result['summary']['rated_point_days'], 14)
                self.assertEqual(self.first_day(result)['two_model_hours'], 0)
        for name in WIND:
            self.model(name)['data'] = ['x', 'x']
        result = self.audit()
        self.assertEqual(result['summary']['unavailable_point_days'], 14)
        self.assertEqual(self.first_day(result)['status'], 'unavailable')

    def test_non_object_forecast_or_models_is_every_day_unavailable(self):
        for forecast in ({'models': []}, {'models': 'x'}, [], 'x'):
            with self.subTest(forecast=forecast):
                result = self.audit(forecast)
                self.assertEqual({d['status'] for p in result['points'] for d in p['days']}, {'unavailable'})
                self.assertEqual(result['summary'], {'point_days': 14, 'rated_point_days': 0,
                                                     'two_model_point_days': 0, 'incomplete_point_days': 14,
                                                     'unavailable_point_days': 14})


if __name__ == '__main__':
    unittest.main()

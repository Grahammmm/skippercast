"""JSON integers outside float range are unavailable evidence, never a crash."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from skippercast.pipeline.forecast_coverage import audit_forecast_coverage

WIND, WAVE = ('gfs_global', 'ecmwf_ifs025'), ('ncep_gfswave016', 'ecmwf_wam')
BIG = json.loads('1' + '0' * 400)


class ForecastCoverageIntegerRangeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
        self.region = {'timezone': 'America/Los_Angeles',
                       'forecast_points': [{'id': 'inner'}, {'id': 'outer'}]}
        zone = ZoneInfo(self.region['timezone'])
        day = self.now.astimezone(zone).date()
        self.times = [int(datetime((day + timedelta(days=d)).year, (day + timedelta(days=d)).month,
                                   (day + timedelta(days=d)).day, hour, tzinfo=zone).timestamp())
                      for d in range(1, 8) for hour in range(7, 14)]
        self.forecast = {'models': {}}
        for model in WIND + WAVE:
            field, unit = ('wind_speed_10m', 'kn') if model in WIND else ('wave_height', 'ft')
            self.forecast['models'][model] = {
                'meta': {'last_run_initialisation_time': self.now.timestamp() - 3600,
                         'data_end_time': self.times[-1]},
                'data': [{'utc_offset_seconds': 0,
                          'hourly_units': {'time': 'unixtime', field: unit, 'wave_period': 's'},
                          'hourly': {'time': list(self.times), field: [5.0] * len(self.times),
                                     'wave_period': [9.0] * len(self.times)}} for _ in range(2)]}

    def audit(self):
        return audit_forecast_coverage(self.forecast, self.region, self.now)

    def test_control_is_complete(self):
        self.assertEqual(self.audit()['summary'], {
            'point_days': 14, 'rated_point_days': 14, 'two_model_point_days': 14,
            'incomplete_point_days': 0, 'unavailable_point_days': 0})

    def test_oversized_metadata_is_unavailable(self):
        for key in ('last_run_initialisation_time', 'data_end_time'):
            for sign in (1, -1):
                with self.subTest(key=key, sign=sign):
                    self.setUp()
                    self.forecast['models']['ecmwf_ifs025']['meta'][key] = sign * BIG
                    summary = self.audit()['summary']
                    self.assertEqual(summary['rated_point_days'], 14)
                    self.assertEqual(summary['two_model_point_days'], 0)
                    self.assertEqual(summary['unavailable_point_days'], 0)
                    for model in WIND:
                        self.forecast['models'][model]['meta'][key] = sign * BIG
                    summary = self.audit()['summary']
                    self.assertEqual(summary['unavailable_point_days'], 14)
                    self.assertEqual(summary['rated_point_days'], 0)
                    self.assertEqual(summary['two_model_point_days'], 0)

    def test_oversized_wave_metadata_keeps_wind_and_other_wave_model(self):
        self.forecast['models']['ecmwf_wam']['meta']['last_run_initialisation_time'] = BIG
        summary = self.audit()['summary']
        self.assertEqual(summary['rated_point_days'], 14)
        self.assertEqual(summary['two_model_point_days'], 0)

    def test_oversized_measurement_is_local(self):
        cases = (('ecmwf_ifs025', 'wind_speed_10m'), ('ecmwf_wam', 'wave_height'),
                 ('ecmwf_wam', 'wave_period'))
        for model, field in cases:
            for sign in (1, -1):
                with self.subTest(model=model, field=field, sign=sign):
                    self.setUp()
                    other = {'ecmwf_ifs025': 'gfs_global', 'ecmwf_wam': 'ncep_gfswave016'}[model]
                    self.forecast['models'][model]['data'][0]['hourly'][field][0] = sign * BIG
                    result = self.audit()
                    first = result['points'][0]['days'][0]
                    self.assertEqual((first['rated_hours'], first['two_model_hours']), (7, 6))
                    self.assertEqual(result['points'][1]['days'][0]['two_model_hours'], 7)
                    self.assertEqual(result['points'][0]['days'][1]['two_model_hours'], 7)
                    self.assertEqual(result['summary']['rated_point_days'], 14)
                    self.assertEqual(result['summary']['two_model_point_days'], 13)
                    self.forecast['models'][other]['data'][0]['hourly'][
                        'wave_height' if field == 'wave_period' else field][0] = sign * BIG
                    # both models of this kind unusable at that hour: not calm, not rated
                    first = self.audit()['points'][0]['days'][0]
                    self.assertEqual((first['rated_hours'], first['two_model_hours']), (6, 6))

    def test_existing_number_contract_unchanged(self):
        self.assertEqual(self.audit()['summary']['rated_point_days'], 14)
        for bad in (True, '5', float('nan'), float('inf'), float('-inf')):
            with self.subTest(bad=bad):
                self.setUp()
                self.forecast['models']['ecmwf_ifs025']['data'][0]['hourly']['wind_speed_10m'][0] = bad
                first = self.audit()['points'][0]['days'][0]
                self.assertEqual((first['rated_hours'], first['two_model_hours']), (7, 6))
        self.setUp()
        self.forecast['models']['ecmwf_ifs025']['data'][0]['hourly']['wind_speed_10m'][0] = 7
        self.assertEqual(self.audit()['points'][0]['days'][0]['two_model_hours'], 7)


if __name__ == '__main__':
    unittest.main()

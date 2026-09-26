"""Regional weather feeds must cover every scored morning at every point."""
from datetime import datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from skippercast.pipeline.forecast_coverage import audit_forecast_coverage


class ForecastCoverageTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
        self.region = {'timezone': 'America/Los_Angeles',
                       'forecast_points': [{'id': 'inner'}, {'id': 'outer'}]}
        zone = ZoneInfo(self.region['timezone'])
        day = self.now.astimezone(zone).date()
        times = [int(datetime((day+timedelta(days=d)).year,
                              (day+timedelta(days=d)).month,
                              (day+timedelta(days=d)).day, hour, tzinfo=zone).timestamp())
                 for d in range(1, 8) for hour in range(7, 14)]
        self.forecast = {'models': {}}
        for model in ('gfs_global', 'ecmwf_ifs025', 'ncep_gfswave016', 'ecmwf_wam025'):
            field, unit = ('wind_speed_10m', 'kn') if model in ('gfs_global', 'ecmwf_ifs025') else ('wave_height', 'ft')
            self.forecast['models'][model] = {
                'meta': {'last_run_initialisation_time': self.now.timestamp()-3600,
                         'data_end_time': times[-1]},
                'data': [{'utc_offset_seconds': 0,
                          'hourly_units': {'time': 'unixtime', field: unit, 'wave_period': 's'},
                          'hourly': {'time': times, field: [5.0]*len(times),
                                     'wave_period': [9.0]*len(times)}} for _ in range(2)]}

    def test_complete_two_model_coverage_for_each_point_and_day(self):
        result = audit_forecast_coverage(self.forecast, self.region, self.now)
        self.assertEqual(result['summary'], {'point_days': 14, 'rated_point_days': 14,
                                             'two_model_point_days': 14, 'incomplete_point_days': 0,
                                             'unavailable_point_days': 0})

    def test_missing_comparison_is_limited_but_retains_rating_coverage(self):
        self.forecast['models']['ecmwf_wam025']['data'][1]['hourly']['wave_height'][-1] = None
        result = audit_forecast_coverage(self.forecast, self.region, self.now)
        self.assertEqual(result['summary']['rated_point_days'], 14)
        self.assertEqual(result['summary']['two_model_point_days'], 13)
        self.assertEqual(result['points'][1]['days'][-1]['status'], 'limited')

    def test_missing_both_wave_models_is_reported_as_incomplete(self):
        for model in ('ncep_gfswave016', 'ecmwf_wam025'):
            self.forecast['models'][model]['data'][0]['hourly']['wave_height'][-1] = None
        result = audit_forecast_coverage(self.forecast, self.region, self.now)
        self.assertEqual(result['summary']['incomplete_point_days'], 1)
        self.assertEqual(result['points'][0]['days'][-1]['rated_hours'], 6)

    def test_stale_run_and_invalid_wave_period_do_not_count(self):
        for model in ('ncep_gfswave016', 'ecmwf_wam025'):
            self.forecast['models'][model]['data'][0]['hourly']['wave_period'][0] = 0
        self.forecast['models']['ecmwf_ifs025']['meta']['last_run_initialisation_time'] = self.now.timestamp()-40*3600
        result = audit_forecast_coverage(self.forecast, self.region, self.now)
        self.assertEqual(result['points'][0]['days'][0]['rated_hours'], 6)
        self.assertEqual(result['summary']['two_model_point_days'], 0)


if __name__ == '__main__':
    unittest.main()

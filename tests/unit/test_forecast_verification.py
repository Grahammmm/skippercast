"""Verification must not turn repeated downloads or missing evidence into skill."""
from datetime import datetime, timezone
import unittest

from skippercast.pipeline.verification import (
    forecast_records, merge_records, observation_records, merge_observations, verify,
    derived_wind_data, derived_wind_records,
)

BASE = 1789984800
STATION = {'id': '46215', 'latitude': 35.2, 'longitude': -120.85, 'variables': ['wave_height']}


def forecast(valid=BASE, model='ncep_gfswave016', cycle=None, **extra):
    cycle = valid - 6 * 3600 if cycle is None else cycle
    row = {'id': f'{model}:{cycle}:46215:{valid}:wave_height', 'model': model, 'cycle': cycle,
           'acquired_at': cycle + 3600, 'station': '46215', 'time': valid,
           'variable': 'wave_height', 'value': 3, 'unit': 'ft', 'grid': [35.2, -120.85],
           'station_coordinates': [35.2, -120.85]}
    return {**row, **extra}


def observation(valid=BASE, **extra):
    return {'id': f'46215:{valid}:wave_height', 'station': '46215', 'time': valid,
            'variable': 'wave_height', 'value': 2, 'unit': 'ft', 'qa': 'provisional_automated',
            'received_at': valid + 120, **extra}


def seven_days():
    times = [BASE + day * 86400 + hour * 3600 for day in range(7) for hour in range(5)]
    return [forecast(t) for t in times], [observation(t) for t in times], times[-1] + 3600


class ForecastVerificationTests(unittest.TestCase):
    def test_source_run_availability_and_settling_are_not_retrieval_time(self):
        data = {'meta': {'last_run_initialisation_time': BASE, 'last_run_availability_time': BASE + 600,
                         'last_run_modification_time': BASE + 550, 'data_end_time': BASE + 7200},
                'points': [{'latitude': 35.2, 'longitude': -120.85, 'hourly_units': {'wave_height': 'ft'},
                            'hourly': {'time': [BASE + 1800, BASE + 3600, BASE + 10800], 'wave_height': [2, 3, 4]}}]}
        with self.assertRaisesRegex(ValueError, 'availability'):
            forecast_records('ncep_gfswave016', data, BASE + 500, [STATION])
        with self.assertRaisesRegex(ValueError, 'settling'):
            forecast_records('ncep_gfswave016', data, BASE + 900, [STATION])
        rows = forecast_records('ncep_gfswave016', data, BASE + 1900, [STATION])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['model_available_at'], BASE + 600)
        self.assertEqual(rows[0]['cycle'], BASE)
        self.assertEqual(rows[0]['acquired_at'], BASE + 1900)
        self.assertEqual(rows[0]['grid_distance_km'], 0)

    def test_invalid_numbers_units_and_duplicate_axes_are_rejected(self):
        data = {'meta': {'last_run_initialisation_time': BASE}, 'points': [
            {'latitude': 35.2, 'longitude': -120.85, 'hourly_units': {'wave_height': 'ft'},
             'hourly': {'time': [BASE + 3600, BASE + 7200], 'wave_height': [True, float('nan')]}}]}
        self.assertEqual(forecast_records('ncep_gfswave016', data, BASE + 1, [STATION]), [])
        data['points'][0]['hourly_units']['wave_height'] = 'm'
        with self.assertRaisesRegex(ValueError, 'unit'):
            forecast_records('ncep_gfswave016', data, BASE + 1, [STATION])
        data['points'][0]['hourly_units']['wave_height'] = 'ft'
        data['points'][0]['hourly']['time'] = [BASE + 3600, BASE + 3600]
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            forecast_records('ncep_gfswave016', data, BASE + 1, [STATION])

    def test_first_forecast_acquisition_remains_immutable_and_ages_out(self):
        old = forecast()
        changed = {**old, 'value': 99, 'acquired_at': BASE + 1}
        self.assertEqual(merge_records([old], [changed], BASE)[0]['value'], 3)
        self.assertEqual(merge_records([old], [], BASE + 31 * 86400), [])

    def test_physical_identity_prevents_alternate_ids_inflating_n(self):
        first = forecast()
        second = {**first, 'id': 'other', 'acquired_at': first['acquired_at'] + 1, 'value': 100}
        obs = observation()
        report = verify([first, second], [obs, {**obs, 'id': 'other-observation'}], BASE + 3600)
        self.assertEqual(report['matched_samples'], 1)
        self.assertEqual(report['groups'][0]['mae'], 1)
        self.assertEqual(report['diagnostics']['duplicate_forecasts'], 1)
        self.assertEqual(report['diagnostics']['duplicate_observations'], 1)

    def test_forecast_and_observation_no_lookahead(self):
        future_acquisition = forecast(acquired_at=BASE + 1)
        self.assertEqual(verify([future_acquisition], [observation()], BASE + 3600)['matched_samples'], 0)
        retrospective_run = forecast(cycle=BASE + 1)
        self.assertEqual(verify([retrospective_run], [observation()], BASE + 3600)['matched_samples'], 0)
        self.assertEqual(verify([forecast()], [observation(received_at=BASE + 7200)], BASE + 3600)['matched_samples'], 0)
        # The observation itself must also postdate forecast acquisition.
        near = forecast(acquired_at=BASE - 60)
        self.assertEqual(verify([near], [observation(BASE - 120)], BASE + 3600)['matched_samples'], 0)

    def test_far_grid_is_excluded_instead_of_becoming_a_local_score(self):
        report = verify([forecast(grid=[36.2, -120.85])], [observation()], BASE + 3600)
        self.assertEqual(report['matched_samples'], 0)
        self.assertEqual(report['diagnostics']['grid_too_distant'], 1)
        self.assertEqual(report['groups'][0]['spatial_match']['excluded_forecasts'], 1)
        self.assertIsNone(report['groups'][0]['mae'])

    def test_legacy_archive_remains_readable_without_claiming_known_spatial_qa(self):
        forecasts, obs, now = seven_days()
        for f in forecasts:
            del f['station_coordinates']
        for o in obs:
            del o['qa']
            del o['received_at']
        report = verify(forecasts, obs, now)
        group = report['groups'][0]
        self.assertEqual(group['n'], 35)
        self.assertEqual(group['status'], 'limited comparability')
        self.assertEqual(group['spatial_match']['unknown_samples'], 35)
        self.assertFalse(group['support']['usable_for_model_comparison'])

    def test_midpoint_observation_used_only_once_in_a_run(self):
        a = forecast()
        b = forecast(BASE + 3600, cycle=a['cycle'])
        report = verify([a, b], [observation(BASE + 1800)], BASE + 7200)
        self.assertEqual(report['matched_samples'], 1)
        self.assertEqual(report['groups'][0]['eligible_forecasts'], 2)
        self.assertEqual(report['groups'][0]['coverage_fraction'], 0.5)

    def test_past_observation_wins_tie_and_offset_is_reported(self):
        report = verify([forecast()], [observation(BASE - 600, value=1), observation(BASE + 600, value=9)], BASE + 3600)
        group = report['groups'][0]
        self.assertEqual(group['bias'], 2)
        self.assertEqual(group['match_time_offset_minutes'], [10, 10])

    def test_pending_hours_do_not_inflate_missing_observation_coverage(self):
        records = [forecast(), forecast(BASE + 3600), forecast(BASE + 7200)]
        report = verify(records, [observation()], BASE + 3700)
        groups = report['groups']
        self.assertEqual(sum(g['eligible_forecasts'] for g in groups), 1)
        self.assertEqual(sum(g['awaiting_observations'] for g in groups), 1)
        self.assertEqual(sum(g['future_forecasts'] for g in groups), 1)
        self.assertEqual(report['summary']['coverage_fraction'], 1)

    def test_unmatched_matured_forecasts_are_visible(self):
        report = verify([forecast()], [], BASE + 3600)
        group = report['groups'][0]
        self.assertEqual(group['status'], 'no matches')
        self.assertEqual(group['unmatched_forecasts'], 1)
        self.assertEqual(group['coverage_fraction'], 0)
        self.assertIsNone(group['bias'])

    def test_sensor_quality_and_gross_missing_sentinels_are_not_measurements(self):
        for obs in [observation(qa='suspect'), observation(value=999), observation(value=True), observation(unit='m')]:
            with self.subTest(obs=obs):
                report = verify([forecast()], [obs], BASE + 3600)
                self.assertEqual(report['matched_samples'], 0)
                self.assertEqual(report['diagnostics']['rejected_observations'], 1)
        self.assertEqual(verify([forecast(value=0)], [observation(value=0)], BASE + 3600)['groups'][0]['mae'], 0)

    def test_new_observations_keep_source_receipt_height_and_provisional_qa(self):
        stamp = datetime.fromtimestamp(BASE, timezone.utc).isoformat()
        station = {**STATION, 'variables': ['wave_height', 'wind_speed_10m'], 'anemometer_height_m': 4.1}
        rows = observation_records(station, [{'time': stamp, 'WVHT': 1, 'WSPD': 5, 'GST': 4}], BASE + 120, 'https://www.ndbc.noaa.gov/')
        self.assertEqual(rows[0]['qa'], 'provisional_automated')
        self.assertEqual(rows[1]['qa'], 'inconsistent_gust')
        self.assertEqual(rows[1]['measurement_height_m'], 4.1)
        self.assertEqual(rows[1]['height_adjustment'], 'none')

    def test_later_observation_revision_records_correction_without_invented_old_receipt(self):
        old = observation()
        revised = observation(value=2.5, received_at=BASE + 900)
        merged = merge_observations([old], [revised], BASE + 1000)[0]
        self.assertEqual(merged['value'], 2.5)
        self.assertEqual(merged['first_received_at'], BASE + 120)
        self.assertEqual(merged['revision_count'], 1)
        self.assertEqual(merge_observations([merged], [old], BASE + 1000)[0], merged)
        del old['received_at']
        self.assertIsNone(merge_observations([old], [revised], BASE + 1000)[0]['first_received_at'])

    def test_provider_derived_wind_keeps_adjustment_and_missing_values(self):
        body = ('#YY MM DD hh mm CHILL HEAT ICE WSPD10 WSPD20\n'
                '#yr mo dy hr mn degC degC cm/hr m/s m/s\n'
                '2026 09 22 16 40 MM MM MM 6 6\n'
                '2026 09 22 16 30 MM MM MM MM MM\n'
                '2026 09 22 16 20 MM MM MM 0 0\n')
        data = derived_wind_data(body, '46053')
        self.assertEqual(len(data['observations']), 2)
        self.assertEqual(data['observations'][1]['value'], 0)
        station = {**STATION, 'id': '46053', 'anemometer_height_m': 4.1,
                   'variables': ['wind_speed_10m'], 'wind_verification': 'ndbc-derived-10m'}
        received = data['observations'][0]['time'] + 600
        records = derived_wind_records(station, data, received, 'https://www.ndbc.noaa.gov/data/derived2/46053.dmv')
        self.assertAlmostEqual(records[0]['value'], 6 * 1.94384449)
        self.assertEqual(records[0]['reference_type'], 'derived_10m')
        self.assertEqual(records[0]['measurement_height_m'], 10)
        self.assertEqual(records[0]['sensor_height_m'], 4.1)
        self.assertEqual(records[0]['qa'], 'provisional_automated')
        self.assertEqual(observation_records(station, [{'time': data['sample_at'], 'WSPD': 5}], received, 'raw'), [])
        with self.assertRaisesRegex(ValueError, 'units'):
            derived_wind_data(body.replace('m/s', 'kn'), '46053')
        with self.assertRaisesRegex(ValueError, 'station'):
            derived_wind_records({**station, 'id': 'wrong'}, data, received, 'wrong')

    def test_derived_wind_comparison_is_labeled_as_an_estimate(self):
        forecasts, obs, now = seven_days()
        forecasts = [{**f, 'variable': 'wind_speed_10m', 'unit': 'kn', 'model': 'gfs_global'} for f in forecasts]
        obs = [{**o, 'variable': 'wind_speed_10m', 'unit': 'kn', 'measurement_height_m': 10, 'reference_type': 'derived_10m'} for o in obs]
        group = verify(forecasts, obs, now)['groups'][0]
        self.assertTrue(group['support']['usable_for_model_comparison'])
        self.assertEqual(group['measurement_comparison'], 'NDBC-derived 10 m wind estimate')

    def test_many_runs_for_one_weather_hour_do_not_establish_support(self):
        forecasts = [forecast(cycle=BASE - (i + 20) * 600) for i in range(40)]
        report = verify(forecasts, [observation()], BASE + 3600)
        group = report['groups'][0]
        self.assertEqual(group['n'], 40)
        self.assertEqual(group['distinct_valid_times'], 1)
        self.assertEqual(group['status'], 'early sample')
        self.assertFalse(group['support']['usable_for_model_comparison'])

    def test_seven_days_of_current_matched_data_enable_descriptive_not_predictive_support(self):
        forecasts, obs, now = seven_days()
        report = verify(forecasts, obs, now)
        group = report['groups'][0]
        self.assertEqual(group['distinct_valid_times'], 35)
        self.assertEqual(group['status'], 'descriptive')
        self.assertTrue(group['support']['usable_for_model_comparison'])
        self.assertFalse(report['summary']['calibrated_probability'])
        self.assertEqual(report['summary']['status'], 'descriptive evidence')
        self.assertEqual(verify(forecasts, obs, now + 4 * 3600)['summary']['status'], 'stale evidence')

    def test_unadjusted_wind_never_yields_10m_model_comparison_support(self):
        forecasts, obs, now = seven_days()
        forecasts = [{**f, 'variable': 'wind_speed_10m', 'unit': 'kn', 'model': 'gfs_global'} for f in forecasts]
        obs = [{**o, 'variable': 'wind_speed_10m', 'unit': 'kn', 'measurement_height_m': 4.1} for o in obs]
        report = verify(forecasts, obs, now)
        self.assertFalse(report['groups'][0]['support']['usable_for_model_comparison'])
        self.assertIn('unadjusted', report['groups'][0]['measurement_comparison'])
        self.assertEqual(report['comparisons'], [])

    def test_model_comparisons_use_common_run_and_hour_not_all_available_cases(self):
        forecasts, obs, now = seven_days()
        second = [{**f, 'model': 'ecmwf_wam', 'id': 'b' + f['id'], 'value': 4} for f in forecasts]
        report = verify(forecasts + second, obs, now)
        comparison = report['comparisons'][0]
        self.assertEqual(comparison['n'], 35)
        self.assertEqual(comparison['lower_error_model'], 'ncep_gfswave016')
        self.assertEqual(comparison['mae_a'], 2)
        self.assertEqual(comparison['mae_b'], 1)
        shifted = [{**f, 'cycle': f['cycle'] - 3600} for f in second]
        self.assertEqual(verify(forecasts + shifted, obs, now)['comparisons'], [])
        early = verify(forecasts[:3] + second[:3], obs[:3], BASE + 3 * 3600)['comparisons'][0]
        self.assertIsNone(early['lower_error_model'])

    def test_empty_archive_does_not_claim_zero_error_or_missing_forecasts(self):
        report = verify([], [], BASE)
        self.assertEqual(report['groups'], [])
        self.assertEqual(report['summary']['eligible_forecasts'], 0)
        self.assertIsNone(report['summary']['coverage_fraction'])
        self.assertEqual(report['summary']['status'], 'collecting history')


if __name__ == '__main__':
    unittest.main()

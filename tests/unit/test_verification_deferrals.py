"""Expected provider update gaps must not become successful-job failure alarms."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from skippercast.pipeline.intelligence import model_verification_records, collection_health
from skippercast.pipeline.verification import ForecastCollectionDeferred, forecast_records

BASE = 1790092800
MODEL = 'gfs_global'
SOURCE = 'model-' + MODEL
STATION = {'id': '46053', 'latitude': 34.246, 'longitude': -119.842, 'variables': ['wind_speed_10m']}


def source(received=BASE+900):
    return {'status': 'ok', 'data_retrieved_at': datetime.fromtimestamp(received, timezone.utc).isoformat(),
            'data': {'meta': {'last_run_initialisation_time': BASE,
                              'last_run_availability_time': BASE+600, 'data_end_time': BASE+7200},
                     'points': [{'latitude': 34.25, 'longitude': -119.85,
                                 'hourly_units': {'wind_speed_10m': 'kn'},
                                 'hourly': {'time': [BASE+3600], 'wind_speed_10m': [6]}}]}}


class VerificationDeferralTests(unittest.TestCase):
    def test_expected_deferral_has_a_stable_code_and_actual_source_clocks(self):
        s = source()
        with self.assertRaises(ForecastCollectionDeferred) as caught:
            forecast_records(MODEL, s['data'], BASE+900, [STATION])
        detail = caught.exception.as_dict()
        self.assertEqual(detail['code'], 'provider_update_settling')
        self.assertEqual(detail['available_at'], BASE+600)
        self.assertEqual(detail['acquired_at'], BASE+900)
        self.assertEqual(detail['retry_at'], BASE+1200)

    def test_timing_deferral_excludes_samples_but_is_a_coverage_gap(self):
        s = source()
        rows = model_verification_records(MODEL, s, 0, [STATION])
        self.assertEqual(rows, [])
        self.assertEqual(s['status'], 'ok')
        self.assertNotIn('verification_issue', s)
        self.assertIn('settling window', s['verification_deferral']['reason'])
        self.assertEqual(collection_health({SOURCE: s}),
                         {'status': 'ok', 'issues': [], 'coverage_gaps': [SOURCE]})

    def test_new_acquisition_after_settling_restores_prospective_collection(self):
        s = source()
        self.assertEqual(model_verification_records(MODEL, s, 0, [STATION]), [])
        s['data_retrieved_at'] = datetime.fromtimestamp(BASE+1200, timezone.utc).isoformat()
        rows = model_verification_records(MODEL, s, 0, [STATION])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['acquired_at'], BASE+1200)
        self.assertNotIn('verification_deferral', s)
        self.assertEqual(collection_health({SOURCE: s})['coverage_gaps'], [])

    def test_bad_units_during_settling_remain_an_error(self):
        s = source()
        s['data']['points'][0]['hourly_units']['wind_speed_10m'] = 'm/s'
        self.assertEqual(model_verification_records(MODEL, s, 0, [STATION]), [])
        self.assertIn('unit mismatch', s['verification_issue'])
        self.assertNotIn('verification_deferral', s)
        self.assertEqual(collection_health({SOURCE: s})['issues'], [SOURCE])

    def test_bad_availability_clock_remains_an_error(self):
        s = source()
        s['data']['meta']['last_run_availability_time'] = BASE+901
        self.assertEqual(model_verification_records(MODEL, s, 0, [STATION]), [])
        self.assertIn('inconsistent', s['verification_issue'])
        self.assertNotIn('verification_deferral', s)
        self.assertEqual(collection_health({SOURCE: s})['status'], 'degraded')

    def test_equal_error_message_does_not_masquerade_as_a_typed_deferral(self):
        s = source()
        with patch('skippercast.pipeline.intelligence.forecast_records',
                   side_effect=ValueError('Forecast is inside the provider ten-minute update settling window')):
            self.assertEqual(model_verification_records(MODEL, s, 0, [STATION]), [])
        self.assertNotIn('verification_deferral', s)
        self.assertEqual(collection_health({SOURCE: s})['issues'], [SOURCE])

    def test_network_failure_is_not_reclassified_by_an_unrelated_deferral(self):
        s = source()
        model_verification_records(MODEL, s, 0, [STATION])
        bad = {'status': 'failed', 'issue': 'Observation source unavailable'}
        health = collection_health({SOURCE: s, 'verify-46053': bad})
        self.assertEqual(health['status'], 'degraded')
        self.assertEqual(health['issues'], ['verify-46053'])
        self.assertEqual(health['coverage_gaps'], [SOURCE])


if __name__ == '__main__':
    unittest.main()

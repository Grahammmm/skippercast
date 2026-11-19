"""F10-09 / SCA-283: a lower-error model is named only when both models' own support qualifies.

Contract: common-case MAEs and their overlap ``n`` stay as measured, but ``lower_error_model``
needs each model group's actual coverage (against ALL its eligible forecasts, not just the
matched ones), current collection and comparability. A believable regression is a pair
denominator that counts matched forecasts only, so 35 of 77 reads as 100% and names a model.
"""
import unittest

from skippercast.pipeline.verification import verify

from tests.unit.test_forecast_verification import BASE, forecast, observation, seven_days


def two_models():
    forecasts, obs, now = seven_days()
    second = [{**f, 'model': 'ecmwf_wam', 'id': 'b' + f['id'], 'value': 4} for f in forecasts]
    return forecasts, second, obs, now


def only(report):
    comparisons = report['comparisons']
    assert len(comparisons) == 1, comparisons
    return comparisons[0]


class LowerErrorModelNeedsBothGroupsTests(unittest.TestCase):
    def assertOverlapKept(self, c):
        # The measured overlap is still reported whatever the conclusion.
        self.assertEqual((c['n'], c['mae_a'], c['mae_b'], c['mae_difference_a_minus_b']), (35, 2, 1, 1))

    def test_fully_supported_pair_names_the_lower_error_model(self):
        first, second, obs, now = two_models()
        c = only(verify(first + second, obs, now))
        self.assertEqual((c['status'], c['lower_error_model']), ('descriptive', 'ncep_gfswave016'))
        self.assertEqual((c['common_case_fraction_a'], c['common_case_fraction_b']), (1.0, 1.0))
        self.assertEqual((c['eligible_forecasts_a'], c['eligible_forecasts_b']), (35, 35))
        self.assertOverlapKept(c)

    def test_sparse_groups_matching_35_of_77_name_no_model(self):
        first, second, obs, now = two_models()
        # 42 more eligible forecasts per model with no observation (hours 10-16 of days 0-5).
        extra = [BASE + d * 86400 + h * 3600 for d in range(6) for h in range(10, 17)]
        unmatched = [forecast(t, model=m, id=f'{m}:{t}:x') for t in extra for m in ('ncep_gfswave016', 'ecmwf_wam')]
        report = verify(first + second + unmatched, obs, now)
        self.assertEqual([g['eligible_forecasts'] for g in report['groups']], [77, 77])
        self.assertFalse(any(g['support']['usable_for_model_comparison'] for g in report['groups']))
        c = only(report)
        self.assertEqual(c['status'], 'limited common-case coverage')
        self.assertIsNone(c['lower_error_model'])
        self.assertEqual(c['common_case_fraction_a'], round(35 / 77, 3))
        self.assertOverlapKept(c)

    def test_stale_collection_names_no_model(self):
        first, second, obs, now = two_models()
        c = only(verify(first + second, obs, now + 4 * 3600))  # newest observation is over 3 h old
        self.assertEqual(c['status'], 'stale collection')
        self.assertIsNone(c['lower_error_model'])
        self.assertOverlapKept(c)

    def test_group_with_unknown_grid_distance_outside_overlap_names_no_model(self):
        first, second, obs, _ = two_models()
        t = BASE + 6 * 86400 + 5 * 3600
        # Not part of the common case, but one model group now has an unverifiable-distance match.
        odd = forecast(t, model='ecmwf_wam', grid=None, id='ecmwf_wam:odd')
        report = verify(first + second + [odd], obs + [observation(t)], t + 3600)
        self.assertFalse(next(g for g in report['groups'] if g['model'] == 'ecmwf_wam')['support']['usable_for_model_comparison'])
        c = only(report)
        self.assertEqual((c['status'], c['lower_error_model']), ('limited group support', None))
        self.assertOverlapKept(c)


if __name__ == '__main__':
    unittest.main()

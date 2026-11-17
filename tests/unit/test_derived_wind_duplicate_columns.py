"""Duplicate derived-wind column names are ambiguous and must be refused."""
import unittest

from skippercast.pipeline.verification import derived_wind_data

STATION = {'id': '46053'}
CHANGED = 'NDBC derived wind fields or units changed'
HEAD = ['YY', 'MM', 'DD', 'hh', 'mm']
HEAD_U = ['yr', 'mo', 'dy', 'hr', 'mn']
TIME = ['2026', '09', '11', '16', '40']


def body(keys, units, *rows):
    return '#' + ' '.join(keys) + '\n#' + ' '.join(units) + '\n' + '\n'.join(' '.join(TIME + r) for r in rows) + '\n'


class DerivedWindDuplicateColumnTests(unittest.TestCase):
    def test_duplicate_wspd10_is_refused_in_either_order_and_unit(self):
        for values in (['4', '60'], ['60', '4']):
            for units in (['m/s', 'm/s'], ['m/s', 'kn'], ['kn', 'm/s']):
                with self.subTest(values=values, units=units), self.assertRaisesRegex(ValueError, CHANGED):
                    derived_wind_data(body(HEAD + ['WSPD10', 'WSPD10'], HEAD_U + units, values), STATION)

    def test_duplicate_unrelated_tail_field_is_refused_before_rows(self):
        keys, units = HEAD + ['CHILL', 'WSPD10', 'CHILL'], HEAD_U + ['degC', 'm/s', 'degC']
        with self.assertRaisesRegex(ValueError, CHANGED):
            derived_wind_data(body(keys, units, ['1', '6']), STATION)  # short row would otherwise be Malformed

    def test_distinct_reordered_tail_columns_are_unchanged(self):
        keys, units = HEAD + ['WSPD10', 'CHILL', 'EXTRA'], HEAD_U + ['m/s', 'degC', 'x']
        data = derived_wind_data(body(keys, units, ['6', 'MM', '1']), STATION)
        self.assertEqual(data['observations'][0]['native_value'], 6.0)

    def test_missing_and_wrong_unit_policy_is_unchanged(self):
        with self.assertRaisesRegex(ValueError, 'No usable'):
            derived_wind_data(body(HEAD + ['WSPD10'], HEAD_U + ['m/s'], ['MM']), STATION)
        with self.assertRaisesRegex(ValueError, CHANGED):
            derived_wind_data(body(HEAD + ['WSPD10'], HEAD_U + ['kn'], ['6']), STATION)


if __name__ == '__main__':
    unittest.main()

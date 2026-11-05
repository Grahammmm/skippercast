"""NDBC derived-wind timestamps are positional, so the header prefix must be exactly the known one."""
import unittest
from datetime import datetime, timezone

from skippercast.pipeline.verification import derived_wind_data

STATION = {'id': '46053'}
KEYS = ['YY', 'MM', 'DD', 'hh', 'mm', 'CHILL', 'WSPD10']
UNITS = ['yr', 'mo', 'dy', 'hr', 'mn', 'degC', 'm/s']
ROW = ['2026', '09', '11', '16', '40', 'MM', '6']
CHANGED = 'NDBC derived wind fields or units changed'
REFUSED = 'NDBC derived wind (fields or units changed|header missing)'  # a non-YY first token fails the older header check


def body(keys=KEYS, units=UNITS, *rows):
    rows = rows or (ROW,)
    return '#' + ' '.join(keys) + '\n#' + ' '.join(units) + '\n' + '\n'.join(' '.join(r) for r in rows) + '\n'


def epoch(*parts):
    return datetime(*parts, tzinfo=timezone.utc).timestamp()


class DerivedWindTimestampHeaderTests(unittest.TestCase):
    def test_canonical_header_is_unchanged(self):
        data = derived_wind_data(body(), STATION)
        self.assertEqual(data['observations'][0]['time'], epoch(2026, 9, 11, 16, 40))
        self.assertEqual(data['sample_at'], '2026-09-11T16:40:00Z')
        self.assertEqual(data['native_unit'], 'm/s')
        self.assertAlmostEqual(data['observations'][0]['value'], 6 * 1.94384449)
        zero = derived_wind_data(body(KEYS, UNITS, ROW[:-1] + ['0']), STATION)
        self.assertEqual(zero['observations'][0]['native_value'], 0.0)

    def test_swapped_day_month_is_refused_instead_of_misdated(self):
        keys = ['YY', 'DD', 'MM', 'hh', 'mm', 'CHILL', 'WSPD10']
        units = ['yr', 'dy', 'mo', 'hr', 'mn', 'degC', 'm/s']
        with self.assertRaisesRegex(ValueError, CHANGED):
            derived_wind_data(body(keys, units, ['2026', '11', '09', '16', '40', 'MM', '6']), STATION)

    def test_each_timestamp_key_position_is_checked(self):
        for i in range(5):
            keys = list(KEYS)
            keys[i] = 'XX'
            with self.subTest(position=i), self.assertRaisesRegex(ValueError, REFUSED):
                derived_wind_data(body(keys), STATION)

    def test_each_timestamp_unit_position_is_checked(self):
        for i in range(5):
            units = list(UNITS)
            units[i] = 'xx'
            with self.subTest(position=i), self.assertRaisesRegex(ValueError, CHANGED):
                derived_wind_data(body(units=units), STATION)

    def test_swapped_hour_minute_units_are_refused(self):
        units = ['yr', 'mo', 'dy', 'mn', 'hr', 'degC', 'm/s']
        with self.assertRaisesRegex(ValueError, CHANGED):
            derived_wind_data(body(units=units), STATION)

    def test_missing_duplicate_or_misnamed_prefix_tokens_are_refused(self):
        cases = {
            'missing minute': (KEYS[:4] + KEYS[5:], UNITS[:4] + UNITS[5:], ROW[:4] + ROW[5:]),
            'duplicate month': (['YY', 'MM', 'MM', 'hh', 'mm', 'WSPD10'], UNITS[:5] + ['m/s'], ROW[:5] + ['6']),
            'lowercase year': (['yy'] + KEYS[1:], UNITS, ROW),
            'timestamp after tail': (['CHILL'] + KEYS[:5] + ['WSPD10'], ['degC'] + UNITS[:5] + ['m/s'], ['MM'] + ROW[:5] + ['6']),
        }
        for name, (keys, units, row) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, REFUSED):
                derived_wind_data(body(keys, units, row), STATION)

    def test_prefix_is_refused_before_any_row_is_interpreted(self):
        keys = ['YY', 'DD', 'MM'] + KEYS[3:]
        units = ['yr', 'dy', 'mo'] + UNITS[3:]
        bad_row = ['2026', '13', '45', '16', '40', 'MM', '6']
        with self.assertRaisesRegex(ValueError, CHANGED):
            derived_wind_data(body(keys, units, bad_row, ['broken']), STATION)

    def test_existing_refusals_are_preserved(self):
        with self.assertRaisesRegex(ValueError, 'header missing'):
            derived_wind_data('', STATION)
        with self.assertRaisesRegex(ValueError, 'header missing'):
            derived_wind_data('#YY MM DD hh mm WSPD10\n#yr mo dy hr mn m/s\n', STATION)
        with self.assertRaises(ValueError):
            derived_wind_data(body(KEYS, UNITS, ['2026', '02', '30', '16', '40', 'MM', '6']), STATION)
        with self.assertRaisesRegex(ValueError, 'No usable'):
            derived_wind_data(body(KEYS, UNITS, ROW[:-1] + ['MM']), STATION)
        with self.assertRaisesRegex(ValueError, CHANGED):
            derived_wind_data(body(units=UNITS[:-1] + ['kn']), STATION)

    def test_boundary_dates_use_utc(self):
        rows = [['2024', '02', '29', '00', '00', 'MM', '1'], ['2026', '12', '31', '23', '59', 'MM', '2']]
        data = derived_wind_data(body(KEYS, UNITS, *rows), STATION)
        self.assertEqual([o['time'] for o in data['observations']],
                         [epoch(2024, 2, 29, 0, 0), epoch(2026, 12, 31, 23, 59)])
        self.assertEqual(data['sample_at'], '2026-12-31T23:59:00Z')

    def test_tail_fields_may_be_extended_reordered_or_spaced_with_tabs(self):
        keys = KEYS[:5] + ['WSPD10', 'ICE', 'CHILL']
        units = UNITS[:5] + ['m/s', 'cm/hr', 'degC']
        data = derived_wind_data(body(keys, units, ['2026', '09', '11', '16', '40', '3', 'MM', 'MM']), STATION)
        self.assertEqual(data['observations'][0]['native_value'], 3.0)
        tabbed = '#YY  MM\tDD hh mm   WSPD10\n#yr mo\tdy hr  mn m/s\n2026\t09 11  16 40\t4\n'
        self.assertEqual(derived_wind_data(tabbed, STATION)['observations'][0]['native_value'], 4.0)


if __name__ == '__main__':
    unittest.main()

"""RF1450-3: a spectral row with repeated numeric frequency labels is refused, never silently overwritten.

Synthetic NDBC text only; the fake client answers known URL suffixes and refuses anything else.
"""
import unittest

from skippercast.pipeline.ocean import spectra, spectral_rows

STATION = '46999'
BASE = f'https://www.ndbc.noaa.gov/data/realtime2/{STATION}'
HEADERS = '#YY  MM DD hh mm\n#yr  mo dy hr mn\n'
DUPLICATE = '^Duplicate spectral frequency$'


class FakeClient:
    def __init__(self, texts):
        self.texts = texts

    def get(self, url):
        suffix = url[len(BASE):] if url.startswith(BASE) else None
        if suffix not in self.texts:
            raise AssertionError('unexpected URL ' + url)
        return self.texts[suffix]


def row(bins, hour=19, minute=40):
    return f'2026 10 31 {hour:02d} {minute:02d} ' + ' '.join(f'{value} ({freq})' for freq, value in bins)


def run(density_rows, direction_rows):
    return spectra(FakeClient({'.data_spec': HEADERS + '\n'.join(density_rows) + '\n',
                               '.swdir': HEADERS + '\n'.join(direction_rows) + '\n'}), STATION)


HEALTHY = [('0.020', '0.5'), ('0.030', '1.25')]
HEALTHY_DIR = [('0.020', '250.0'), ('0.030', '260.0')]


class RepeatedFrequencyTests(unittest.TestCase):
    def test_repeated_frequency_refused_before_overwrite(self):
        cases = {
            'identical label, different values': [('0.020', '0.5'), ('0.020', '99.0')],
            'identical label, equal values': [('0.020', '0.5'), ('0.020', '0.5')],
            'trailing zero alias': [('0.020', '0.5'), ('0.0200', '99.0')],
            'exponent alias': [('0.02', '0.5'), ('2e-2', '99.0')],
            'reversed order': [('0.0200', '99.0'), ('0.030', '1.0'), ('0.020', '0.5')],
        }
        for name, bins in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, DUPLICATE):
                spectral_rows(row(bins))

    def test_spectra_refuses_duplicate_density_or_direction(self):
        bad = [('0.020', '0.5'), ('0.0200', '99.0')]
        good_later = row(HEALTHY, hour=20, minute=10)
        with self.subTest('density'), self.assertRaisesRegex(ValueError, DUPLICATE):
            run([row(HEALTHY), row(bad, hour=20, minute=10)], [row(HEALTHY_DIR), row(HEALTHY_DIR, hour=20, minute=10)])
        with self.subTest('direction'), self.assertRaisesRegex(ValueError, DUPLICATE):
            run([row(HEALTHY), good_later],
                [row(HEALTHY_DIR), row([('0.020', '250.0'), ('2e-2', '251.0')], hour=20, minute=10)])

    def test_distinct_nearby_bins_keep_pairing_contract(self):
        frame, = run([row([('0.0325', '1.10'), ('0.0335', '1.20')])],
                     [row([('0.0328', '250.0'), ('0.050', '270.0')])])['frames']
        self.assertEqual(frame['bins'], [[0.0325, 1.1, 250.0]])
        self.assertEqual((frame['paired_bins'], frame['total_bins']), (1, 2))

    def test_existing_frequency_and_row_limits_unchanged(self):
        for freq in ('0.000', '1e999'):
            with self.subTest(freq), self.assertRaisesRegex(ValueError, '^Invalid spectral frequency$'):
                spectral_rows(row([(freq, '0.5'), ('0.030', '1.25')]))
        text = HEADERS + '\n2026 10 31 19 40\n' + row(HEALTHY) + '\n'
        self.assertEqual(len(spectral_rows(text)[next(iter(spectral_rows(text)))]), 2)
        many = '\n'.join(row(HEALTHY, hour=h, minute=0) for h in range(14))
        self.assertEqual(len(spectral_rows(many)), 12)


if __name__ == '__main__':
    unittest.main()

"""SC2007-12: NDBC spectra pair density and direction bins to 0.001 Hz and record paired/total bins.

Synthetic NDBC text only; the fake client answers known URL suffixes and refuses anything else.
"""
from datetime import datetime, timezone
import unittest

from skippercast.pipeline.ocean import pair_bins, spectra, spectral_rows

STATION = '46999'
BASE = f'https://www.ndbc.noaa.gov/data/realtime2/{STATION}'
HEADERS = '#YY  MM DD hh mm\n#yr  mo dy hr mn\n'


class FakeClient:
    """URL suffix -> text; an unknown URL raises."""
    def __init__(self, texts):
        self.texts = texts
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        suffix = url[len(BASE):] if url.startswith(BASE) else None
        if suffix not in self.texts:
            raise AssertionError('unexpected URL ' + url)
        return self.texts[suffix]


def row(bins, hour=19, minute=40, separation=None):
    """One NDBC row: 'YYYY MM DD hh mm [sep] value (freq) ...'; freq labels are passed as text."""
    head = f'2026 10 31 {hour:02d} {minute:02d}' + (f' {separation}' if separation else '')
    return head + ' ' + ' '.join(f'{value} ({freq})' for freq, value in bins)


def epoch(hour=19, minute=40):
    return int(datetime(2026, 10, 31, hour, minute, tzinfo=timezone.utc).timestamp())


def run(density_rows, direction_rows):
    client = FakeClient({'.data_spec': HEADERS + '\n'.join(density_rows) + '\n',
                         '.swdir': HEADERS + '\n'.join(direction_rows) + '\n'})
    result = spectra(client, STATION)
    assert client.urls == [BASE + '.data_spec', BASE + '.swdir'], client.urls
    return result


class PairingTests(unittest.TestCase):
    def test_identical_labels_keep_todays_bins_and_all_paired(self):
        result = run([row([('0.020', '0.50'), ('0.030', '1.25'), ('0.040', '2.00')], separation='9.999')],
                     [row([('0.020', '250.0'), ('0.030', '260.0'), ('0.040', '270.0')])])
        frame, = result['frames']
        self.assertEqual(frame, {'time': epoch(), 'bins': [[0.02, 0.5, 250.0], [0.03, 1.25, 260.0], [0.04, 2.0, 270.0]],
                                 'paired_bins': 3, 'total_bins': 3})
        self.assertEqual((result['paired_bins'], result['total_bins']), (3, 3))
        self.assertEqual(result['fields'], ['frequency_hz', 'density_m2_per_hz', 'mean_direction_from_degrees'])
        self.assertEqual((result['station'], result['provider'], result['sample_at']), (STATION, 'NOAA NDBC', '2026-10-31T19:40:00Z'))

    def test_labels_within_tolerance_pair_under_the_density_label(self):
        frame, = run([row([('0.0325', '1.10'), ('0.040', '2.00')])],
                     [row([('0.033', '250.0'), ('0.040', '270.0')])])['frames']
        self.assertEqual(frame['bins'], [[0.0325, 1.1, 250.0], [0.04, 2.0, 270.0]])
        self.assertEqual((frame['paired_bins'], frame['total_bins']), (2, 2))

    def test_labels_beyond_tolerance_do_not_pair_and_are_counted(self):
        result = run([row([('0.0325', '1.10'), ('0.040', '2.00')])],
                     [row([('0.035', '250.0'), ('0.040', '270.0')])])
        frame, = result['frames']
        self.assertEqual(frame['bins'], [[0.04, 2.0, 270.0]])
        self.assertEqual(frame['paired_bins'], frame['total_bins'] - 1)
        self.assertEqual((result['paired_bins'], result['total_bins']), (1, 2))

    def test_tolerance_edge_is_inclusive(self):
        self.assertEqual(pair_bins({0.030: 1.0}, {0.031: 200.0}), [(0.030, 1.0, 200.0)])
        self.assertEqual(pair_bins({0.030: 1.0}, {0.0311: 200.0}), [(0.030, 1.0, None)])

    def test_direction_bin_is_used_once_by_the_nearer_density_bin(self):
        result = run([row([('0.0325', '1.10'), ('0.0335', '1.20')])], [row([('0.0328', '250.0'), ('0.050', '270.0')])])
        frame, = result['frames']
        self.assertEqual(frame['bins'], [[0.0325, 1.1, 250.0]])
        self.assertEqual((frame['paired_bins'], frame['total_bins']), (1, 2))
        self.assertEqual(pair_bins({0.0325: 1.1, 0.0335: 1.2}, {0.0328: 250.0}), [(0.0325, 1.1, 250.0), (0.0335, 1.2, None)])

    def test_equal_distance_tie_takes_the_lower_direction_label(self):
        self.assertEqual(pair_bins({0.0325: 1.0}, {0.033: 270.0, 0.032: 250.0}), [(0.0325, 1.0, 250.0)])
        self.assertEqual(pair_bins({0.0325: 1.0, 0.0335: 2.0}, {0.033: 270.0, 0.032: 250.0}),
                         [(0.0325, 1.0, 250.0), (0.0335, 2.0, 270.0)])

    def test_energy_fills_are_dropped_after_pairing(self):
        frame, = run([row([('0.020', '999.00'), ('0.030', '-1'), ('0.040', '0.80')])],
                     [row([('0.020', '250.0'), ('0.030', '260.0'), ('0.040', '270.0')])])['frames']
        self.assertEqual(frame['bins'], [[0.04, 0.8, 270.0]])
        self.assertEqual((frame['paired_bins'], frame['total_bins']), (3, 3))

    def test_direction_fill_and_range(self):
        frame, = run([row([('0.020', '0.5'), ('0.030', '0.6'), ('0.040', '0.7'), ('0.050', '0.8')])],
                     [row([('0.020', '999.0'), ('0.030', '360'), ('0.040', '361'), ('0.050', '0')])])['frames']
        self.assertEqual(frame['bins'], [[0.03, 0.6, 360.0], [0.05, 0.8, 0.0]])
        self.assertEqual((frame['paired_bins'], frame['total_bins']), (4, 4))

    def test_totals_sum_only_kept_frames(self):
        result = run([row([('0.020', '0.5'), ('0.030', '0.6')], minute=10),
                      row([('0.020', '999.00'), ('0.030', '999.00')], minute=40),
                      row([('0.020', '0.5'), ('0.0325', '0.6'), ('0.040', '0.7')], hour=20, minute=10)],
                     [row([('0.020', '250.0'), ('0.030', '260.0')], minute=10),
                      row([('0.020', '250.0'), ('0.030', '260.0')], minute=40),
                      row([('0.020', '250.0'), ('0.035', '260.0'), ('0.040', '270.0')], hour=20, minute=10)])
        self.assertEqual([(f['time'], f['paired_bins'], f['total_bins']) for f in result['frames']],
                         [(epoch(19, 10), 2, 2), (epoch(20, 10), 2, 3)])
        self.assertEqual((result['paired_bins'], result['total_bins']), (4, 5))
        self.assertEqual(result['sample_at'], '2026-10-31T20:10:00Z')

    def test_density_epoch_missing_from_directions_has_no_frame(self):
        two = [('0.020', '0.5'), ('0.030', '0.6')]
        result = run([row(two, minute=10), row(two, minute=40)], [row(two, minute=40), row(two, minute=50)])
        self.assertEqual([f['time'] for f in result['frames']], [epoch()])

    def test_all_labels_mismatched_is_the_existing_error(self):
        with self.assertRaisesRegex(ValueError, '^No time-aligned density/direction spectra$'):
            run([row([('0.020', '0.5'), ('0.030', '0.6')])], [row([('0.025', '250.0'), ('0.035', '260.0')])])

    def test_unknown_url_is_refused(self):
        with self.assertRaisesRegex(AssertionError, 'unexpected URL'):
            spectra(FakeClient({'.data_spec': row([('0.020', '0.5'), ('0.030', '0.6')])}), STATION)


class SpectralRowsTests(unittest.TestCase):
    def test_headers_and_short_lines_skipped_separation_not_a_bin(self):
        text = HEADERS + '\n2026 10 31 19 40\n' + row([('0.020', '0.000'), ('0.030', '1.25')], separation='9.999') + '\n'
        self.assertEqual(spectral_rows(text), {epoch(): {0.02: 0.0, 0.03: 1.25}})

    def test_zero_frequency_is_invalid(self):
        with self.assertRaisesRegex(ValueError, '^Invalid spectral frequency$'):
            spectral_rows(row([('0.000', '0.5'), ('0.030', '1.25')]))

    def test_fourteen_rows_give_twelve_epochs(self):
        text = '\n'.join(row([('0.020', '0.5'), ('0.030', '0.6')], hour=h, minute=0) for h in range(14))
        self.assertEqual(sorted(spectral_rows(text)), [epoch(h, 0) for h in range(12)])

    def test_only_headers_is_no_observations(self):
        with self.assertRaisesRegex(ValueError, '^No spectral observations$'):
            spectral_rows(HEADERS)


if __name__ == '__main__':
    unittest.main()

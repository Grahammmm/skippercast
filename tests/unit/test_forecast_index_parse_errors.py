"""Forecast index admission: malformed or out-of-order rows are refused by name, not as bare errors.

Contract: parse_gfs_idx / parse_ecmwf_index either return exact byte ranges or raise
ValueError('Invalid forecast index ...'); they never hand back an inverted range and never
leak IndexError / KeyError / AttributeError from a bad row.
"""
import json
import unittest

from skippercast.forecast import fetch

PREFIX = 'Invalid forecast index'


def idx_line(number, offset, var='UGRD', level='10 m above ground'):
    return f'{number}:{offset}:d=2026112000:{var}:{level}:3 hour fcst:'


def idx(*offsets):
    return '\n'.join(idx_line(i, o) for i, o in enumerate(offsets, 1)) + '\n'


def lines(*rows):
    return '\n'.join(json.dumps(r) for r in rows)


def row(param, offset, length=10, **extra):
    return {'param': param, '_offset': offset, '_length': length, **extra}


class GfsIndexTests(unittest.TestCase):
    def refused(self, text):
        with self.assertRaises(ValueError) as ctx:
            fetch.parse_gfs_idx(text)
        self.assertTrue(str(ctx.exception).startswith(PREFIX), str(ctx.exception))

    def test_healthy_index_is_unchanged_with_open_ended_last_row(self):
        # Control: a tightened parser must not alter the ranges of a good index.
        text = idx_line(1, 0) + '\n\n' + idx_line(2, 100, 'VGRD') + '\n' + idx_line(3, 250, 'GUST', 'surface') + '\n'
        self.assertEqual(fetch.parse_gfs_idx(text), [
            ('UGRD', '10 m above ground', '3 hour fcst', 0, 99),
            ('VGRD', '10 m above ground', '3 hour fcst', 100, 249),
            ('GUST', 'surface', '3 hour fcst', 250, None)])
        self.assertEqual(fetch.parse_gfs_idx(idx(7)), [('UGRD', '10 m above ground', '3 hour fcst', 7, None)])
        self.assertEqual(fetch.parse_gfs_idx(''), [])
        # Extra trailing colon fields (NOAA adds some) are not a refusal.
        self.assertEqual(fetch.parse_gfs_idx(idx_line(1, 5) + 'extra:\n')[0][3:], (5, None))

    def test_non_increasing_offsets_are_refused_not_inverted(self):
        # Bug caught: next_start - 1 < start gave (500, 99) that select_gfs passed to the Range header.
        for offsets in ((500, 100), (100, 100), (0, 100, 100), (0, 100, 50), (0, 100, 200, 150)):
            with self.subTest(offsets=offsets):
                self.refused(idx(*offsets))

    def test_inverted_rows_never_reach_selection(self):
        with self.assertRaises(ValueError):
            fetch.select_gfs(fetch.parse_gfs_idx(idx(500, 100)), 'UGRD', '10 m above ground')

    def test_short_lines_are_refused_by_name(self):
        # Bug caught: parts[3..5] on a short line escaped as a bare IndexError.
        for bad in ('1:0:d=x', '1', '1:0:d=x:UGRD:10 m above ground', '1:0'):
            for text in (bad + '\n', idx(0) + bad + '\n', bad + '\n' + idx(0)):
                with self.subTest(text=text):
                    self.refused(text)

    def test_non_integer_or_negative_start_offsets_are_refused(self):
        # Bug caught: int('abc') escaped as an unnamed ValueError; a negative start was accepted.
        for bad in ('abc', '', '1.5', '0x10', '-1', '-100'):
            text = idx_line(1, bad) + '\n'
            with self.subTest(offset=bad):
                self.refused(text)
            with self.subTest(offset=bad, position='later'):
                self.refused(idx_line(1, 0) + '\n' + text)

    def test_zero_start_is_valid(self):
        self.assertEqual(fetch.parse_gfs_idx(idx(0, 1)), [
            ('UGRD', '10 m above ground', '3 hour fcst', 0, 0),
            ('UGRD', '10 m above ground', '3 hour fcst', 1, None)])


class EcmwfIndexTests(unittest.TestCase):
    def refused(self, text):
        with self.assertRaises(ValueError) as ctx:
            fetch.parse_ecmwf_index(text)
        self.assertTrue(str(ctx.exception).startswith(PREFIX), str(ctx.exception))

    def test_healthy_index_is_unchanged(self):
        # Control: first row wins, missing levtype means surface, non-surface rows need no fields.
        text = lines(row('10u', 0, 100), row('10u', 500, 5), row('10v', 100, 50, levtype='sfc'),
                     {'levtype': 'pl'}, row('msl', 200, 10, levtype='pl', levelist='500'))
        self.assertEqual(fetch.parse_ecmwf_index(text), {'10u': (0, 99), '10v': (100, 149)})

    def test_rows_that_are_not_objects_are_refused(self):
        # Bug caught: row.get on a list/number/string/null escaped as AttributeError.
        for bad in ([1, 2], 5, 'text', None, True):
            with self.subTest(row=bad):
                self.refused(lines(bad))
                self.refused(lines(row('10u', 0), bad))

    def test_rows_missing_required_fields_are_refused_by_name(self):
        # Bug caught: a bare KeyError for param / _offset / _length (checked after the levtype skip).
        for missing in ('param', '_offset', '_length'):
            bad = row('10u', 0)
            del bad[missing]
            with self.subTest(missing=missing):
                self.refused(lines(bad))
                self.refused(lines(row('10v', 100), bad))
        self.refused(lines({}))

    def test_named_byte_range_refusal_is_unchanged(self):
        # Control: the existing numeric-domain refusal keeps its own message.
        with self.assertRaisesRegex(ValueError, '^Invalid ECMWF index byte range$'):
            fetch.parse_ecmwf_index(lines(row('10u', True)))


if __name__ == '__main__':
    unittest.main()

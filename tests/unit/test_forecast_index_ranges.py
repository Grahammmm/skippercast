"""ECMWF index admission: malformed byte-range numbers are refused before planning."""
from datetime import datetime, timezone
import json
import unittest
from unittest import mock

from skippercast.forecast import fetch
from skippercast.forecast.models import MODELS

MESSAGE = 'Invalid ECMWF index byte range'
CANARY = 'canary_param_zq9'
BAD = [-1, -10, 0, True, False, None, '10', '', [], [1], {}, {'a': 1}, 0.5, 10.0, 0.0,
       float('nan'), float('inf'), float('-inf')]


def lines(*rows):
    return '\n'.join(json.dumps(r) for r in rows)


def row(param, offset, length=10, **extra):
    return {'param': param, '_offset': offset, '_length': length, **extra}


class IndexRangeTests(unittest.TestCase):
    def test_ecmwf_numeric_range_domain_refuses(self):
        for bad in BAD:
            for field in ('_offset', '_length'):
                if field == '_offset' and bad == 0:
                    continue  # zero offset is valid
                with self.subTest(field=field, bad=repr(bad)):
                    r = row(CANARY, 0, 10)
                    r[field] = bad
                    with self.assertRaises(ValueError) as ctx:
                        fetch.parse_ecmwf_index(lines(r))
                    self.assertEqual(str(ctx.exception), MESSAGE)

    def test_invalid_later_or_duplicate_row_refuses_whole_index(self):
        for text in (lines(row('10u', 0), row(CANARY, -1), row('10v', 20)),
                     lines(row(CANARY, 0), row(CANARY, 10, 0)),
                     lines(row(CANARY, 0), row(CANARY, 10.0))):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as ctx:
                    fetch.parse_ecmwf_index(text)
                self.assertEqual(str(ctx.exception), MESSAGE)
                self.assertNotIn(CANARY, str(ctx.exception))

    def test_valid_integer_ranges_preserve_parser_contract(self):
        big = 2 ** 70
        text = '\n  \n'.join([lines(row('10u', 0, 1)), lines(row('10v', 10, levtype='sfc')),
                              lines(row('10u', 99, 5)), lines(row('2t', big, big))])
        index = fetch.parse_ecmwf_index(text)
        self.assertEqual(index, {'10u': (0, 0), '10v': (10, 19), '2t': (big, 2 * big - 1)})
        self.assertEqual(list(index), ['10u', '10v', '2t'])

    def test_filtered_rows_do_not_require_numeric_metadata(self):
        text = lines({'param': 'x', 'levtype': 'pl', 'levelist': '500'},
                     {'param': 'y', 'levtype': 'ml', '_offset': -5, '_length': 'bad'},
                     row('10u', 100, levtype='sfc'))
        self.assertEqual(fetch.parse_ecmwf_index(text), {'10u': (100, 109)})

    def test_plan_step_refuses_before_downloading_fields(self):
        model = MODELS['ecmwf_ifs025']
        cycle = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
        selectors = [('wind_u', ('10u',))]
        cases = [(-10, 10), (0, 0), (10, -3), (0.5, 10), (True, 10), (0, True)]
        for offset, length in cases:
            with self.subTest(offset=offset, length=length):
                calls = []

                def fake_http(url, **kwargs):
                    calls.append(url)
                    return lines(row('10u', offset, length, levtype='sfc')).encode()

                with mock.patch.object(fetch, 'http', fake_http), \
                        mock.patch.object(fetch, 'ecmwf_base', lambda m, c: fetch.ECMWF_AWS):
                    with self.assertRaises(ValueError) as ctx:
                        fetch.plan_step(model, cycle, 24, selectors)
                self.assertEqual(str(ctx.exception), MESSAGE)
                self.assertEqual(calls, [fetch.index_url(model, cycle, 24, fetch.ECMWF_AWS)])
        calls = []

        def healthy(url, **kwargs):
            calls.append(url)
            return lines(row('10u', 0, 10)).encode()

        with mock.patch.object(fetch, 'http', healthy), mock.patch.object(fetch, 'ecmwf_base', lambda m, c: fetch.ECMWF_AWS):
            plan = fetch.plan_step(model, cycle, 24, selectors)
        self.assertEqual(plan, [('wind_u', fetch.ecmwf_url(model, cycle, 24, fetch.ECMWF_AWS), (0, 9))])
        self.assertEqual(len(calls), 1)

    def test_missing_keys_and_json_errors_keep_existing_exceptions(self):
        with self.assertRaises(KeyError):
            fetch.parse_ecmwf_index(lines({'param': '10u', '_length': 10}))
        with self.assertRaises(KeyError):
            fetch.parse_ecmwf_index(lines({'param': '10u', '_offset': 0}))
        with self.assertRaises(json.JSONDecodeError):
            fetch.parse_ecmwf_index('{not json')


if __name__ == '__main__':
    unittest.main()

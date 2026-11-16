"""ECMWF index admission: explicitly non-surface rows are never planned as surface fields."""
from datetime import datetime, timezone
import json
import unittest
from unittest import mock

from skippercast.forecast import fetch
from skippercast.forecast.models import MODELS


def lines(*rows):
    return '\n'.join(json.dumps(r) for r in rows)


def row(param, offset, length=10, **extra):
    return {'param': param, '_offset': offset, '_length': length, **extra}


class IndexLevelTests(unittest.TestCase):
    def test_non_surface_rows_without_levelist_cannot_shadow_surface(self):
        control = fetch.parse_ecmwf_index(lines(row('10u', 0, levtype='pl', levelist='500'), row('10u', 100, levtype='sfc')))
        self.assertEqual(control, {'10u': (100, 109)})
        for levtype in ('pl', 'ml'):
            with self.subTest(levtype=levtype):
                text = lines(row('10u', 0, levtype=levtype), row('10u', 100, levtype='sfc'))
                self.assertEqual(fetch.parse_ecmwf_index(text), control)
                reverse = lines(row('10u', 100, levtype='sfc'), row('10u', 0, levtype=levtype))
                self.assertEqual(fetch.parse_ecmwf_index(reverse), control)

    def test_explicit_non_surface_types_are_skipped_before_surface_fields(self):
        for levtype in ('pl', 'ml', None, '', False):
            for extra in ({}, {'levelist': '500'}):
                with self.subTest(levtype=levtype, extra=extra):
                    bare = {'levtype': levtype, **extra}
                    self.assertEqual(fetch.parse_ecmwf_index(lines(bare)), {})
                    text = lines(bare, row('10u', 100, levtype='sfc'))
                    self.assertEqual(fetch.parse_ecmwf_index(text), {'10u': (100, 109)})
        self.assertEqual(fetch.parse_ecmwf_index(''), {})
        self.assertEqual(fetch.parse_ecmwf_index('\n  \n'), {})

    def test_missing_levtype_and_explicit_surface_preserve_compatibility(self):
        text = lines(row('10u', 0), row('10v', 10, levtype='sfc'), row('2t', 20, levtype='sfc', levelist='2'),
                     row('10u', 30, levtype='sfc'))
        index = fetch.parse_ecmwf_index(text)
        self.assertEqual(index, {'10u': (0, 9), '10v': (10, 19), '2t': (20, 29)})
        self.assertEqual(list(index), ['10u', '10v', '2t'])

    def test_plan_step_uses_eligible_surface_range(self):
        model = MODELS['ecmwf_ifs025']
        cycle = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
        text = lines(row('10u', 0, levtype='pl'), row('10u', 100, levtype='sfc'), row('gust_a', 200, levtype='ml'))
        calls = []

        def fake_http(url, **kwargs):
            calls.append(url)
            return text.encode()

        with mock.patch.object(fetch, 'http', fake_http), mock.patch.object(fetch, 'ecmwf_base', lambda m, c: fetch.ECMWF_AWS):
            plan = fetch.plan_step(model, cycle, 24, [('wind_u', ('10u',)), ('gust', ('gust_a', '10u')), ('gone', ('gust_a',))])
        self.assertEqual(calls, [fetch.index_url(model, cycle, 24, fetch.ECMWF_AWS)])
        url = fetch.ecmwf_url(model, cycle, 24, fetch.ECMWF_AWS)
        self.assertEqual(plan, [('wind_u', url, (100, 109)), ('gust', url, (100, 109))])

    def test_eligible_row_error_paths_unchanged(self):
        with self.assertRaises(json.JSONDecodeError):
            fetch.parse_ecmwf_index('{not json')
        with self.assertRaises(KeyError):
            fetch.parse_ecmwf_index(lines({'levtype': 'sfc', '_offset': 0, '_length': 10}))
        with self.assertRaises(KeyError):
            fetch.parse_ecmwf_index(lines({'param': '10u', '_offset': 0}))


if __name__ == '__main__':
    unittest.main()

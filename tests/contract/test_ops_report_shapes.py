"""scripts/ops_report.py: an unexpected SQL or GitHub answer shape is named, never a traceback."""
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

from scripts import ops_report
from tests.contract.test_ops_report_numbers import NORMAL, NORMAL_REPORT

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
ENV = {'CF_ANALYTICS_TOKEN': 'token-value', 'CLOUDFLARE_ACCOUNT_ID': 'acct123'}
SENTINEL = 'SENTINEL-body-7f3a'
HEARTBEAT = [{'region': 'CA', 'pushed_at': '2026-10-05 09:00:00', 'heartbeat_age_s': '1800',
              'last_message_age_s': 1790, 'messages_24h': '512000'}]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sql_opener(bodies, seen):
    """Raw answer bytes per QUERIES key; any other query answers {"data": []}."""
    def opener(request, timeout):
        key = next(k for k, sql in ops_report.QUERIES.items() if sql == request.data.decode())
        seen.append(key)
        return FakeResponse(bodies.get(key, b'{"data": []}'))
    return opener


def github_answer(body):
    return lambda request, timeout: FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())


def run(bodies, github=None, env=None):
    seen, out = [], io.StringIO()
    with redirect_stdout(out):
        code = ops_report.main([], dict(ENV, **(env or {})), opener=sql_opener(bodies, seen),
                               github_opener=github or github_answer([]), now=NOW)
    return code, out.getvalue(), seen


def rows_body(rows):
    return json.dumps({'meta': [], 'data': rows, 'rows': len(rows)}).encode()


class SqlAnswerShapeTests(unittest.TestCase):
    BAD = {
        'a list': json.dumps([SENTINEL]).encode(),
        'an empty list': b'[]',
        'a string': json.dumps(f'text {SENTINEL}').encode(),
        'a number': b'42',
        'null': b'null',
        'data a string': json.dumps({'data': SENTINEL}).encode(),
        'data null': json.dumps({'data': None, 'note': SENTINEL}).encode(),
        'data numbers': json.dumps({'data': [1, 2], 'note': SENTINEL}).encode(),
        'data a dict': json.dumps({'data': {'route': SENTINEL}}).encode(),
        'data mixed rows': json.dumps({'data': [{'route': '/a'}, SENTINEL]}).encode(),
        'data list rows': json.dumps({'data': [[SENTINEL]]}).encode(),
        'not JSON': f'<html>{SENTINEL}</html>'.encode(),
    }

    def test_unexpected_shape_is_named_and_later_queries_do_not_run(self):
        for name, body in self.BAD.items():
            with self.subTest(name=name):
                code, out, seen = run({'routes': body})
                self.assertEqual(code, 1)
                self.assertEqual(seen, ['routes'], 'later queries not run')
                self.assertNotIn('Traceback', out)
                self.assertNotIn(SENTINEL, out, 'the error line never carries the body')
                if name != 'not JSON':
                    self.assertEqual(out, '::error title=Ops report::Analytics Engine SQL API unavailable for routes: '
                                          'unexpected answer shape\n')
                else:
                    self.assertTrue(out.startswith('::error title=Ops report::Analytics Engine SQL API unavailable '
                                                   'for routes: '), out)

    def test_a_later_query_with_a_bad_shape_names_that_query(self):
        code, out, seen = run({'routes': rows_body(NORMAL['routes']), 'queue': json.dumps({'data': 'x'}).encode()})
        self.assertEqual(code, 1)
        self.assertEqual(seen, ['routes', 'llm', 'queue'])
        self.assertEqual(out, '::error title=Ops report::Analytics Engine SQL API unavailable for queue: '
                              'unexpected answer shape\n')

    def test_an_answer_without_data_is_no_rows(self):
        code, out, seen = run({'routes': b'{}', 'llm': json.dumps({'meta': [], 'rows': 0}).encode()})
        self.assertEqual(code, 0)
        self.assertEqual(seen, list(ops_report.QUERIES))
        self.assertIn('## Requests by route (last 24 h)\n\n_No data points in this window._\n', out)
        self.assertNotIn('::error', out)

    def test_valid_answers_render_exactly_as_before(self):
        code, out, _ = run({key: rows_body(rows) for key, rows in NORMAL.items()})
        self.assertEqual(code, 0)
        self.assertEqual(out, NORMAL_REPORT + '\n')
        self.assertEqual(ops_report.query('x', account='a', token='t', opener=lambda r, timeout: FakeResponse(b'{}')), [])


class GithubAnswerShapeTests(unittest.TestCase):
    def fleet(self, body):
        code, out, _ = run({'fleet_ais': rows_body(HEARTBEAT)}, github_answer(body), {'GITHUB_REPOSITORY': 'example/sc'})
        self.assertEqual(code, 0)
        self.assertNotIn('Traceback', out)
        return next(line for line in out.splitlines() if line.startswith('Fleet AIS:'))

    def test_malformed_issue_answers_read_issue_unknown(self):
        for body in ([{}], [1], [None], ['x'], [[7]], [{'number': 'x'}], [{'number': None}], [{'number': 7.5}],
                     [{'number': True}], [{'number': '²'}], [{'number': '-3'}], {'message': 'Bad credentials'},
                     {}, 'text', 7, None, b'not json'):
            with self.subTest(body=body):
                self.assertEqual(ops_report.open_fleet_issue('example/sc', None, github_answer(body)), None)
                self.assertTrue(self.fleet(body).endswith('; fleet-ais-stale issue unknown.'))

    def test_a_numbered_issue_and_an_empty_list(self):
        for body, issue in (([{'number': 7}], '#7'), ([{'number': '7'}], '#7'), ([{'number': 7, 'x': 1}, 'junk'], '#7')):
            with self.subTest(body=body):
                self.assertEqual(ops_report.open_fleet_issue('example/sc', None, github_answer(body)), issue)
        self.assertTrue(self.fleet([{'number': 7}]).endswith('; open fleet-ais-stale issue #7.'))
        self.assertEqual(ops_report.open_fleet_issue('example/sc', None, github_answer([])), '')
        self.assertTrue(self.fleet([]).endswith('; no open fleet-ais-stale issue.'))


if __name__ == '__main__':
    unittest.main()

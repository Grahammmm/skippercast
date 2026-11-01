"""scripts/ops_report.py: non-finite or non-numeric Analytics numbers render as a dash and are skipped from totals."""
import unittest
from datetime import datetime, timezone

from scripts import ops_report

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)

# The routes/llm fixture tests/contract/test_ops_report.py uses, and the report main rendered for it before.
NORMAL = {
    'routes': [
        {'route': '/feeds/*', 'requests': '1200', 's2xx': '1190', 's3xx': '0', 's4xx': '4', 's5xx': '6', 'p95_ms': 81.5},
        {'route': '/api/om/v1/forecast', 'requests': 300, 's2xx': 300, 's3xx': 0, 's4xx': 0, 's5xx': 0, 'p95_ms': 412.25}],
    'llm': [{'feature': 'boat_lookup', 'model': 'claude-sonnet-5', 'outcome': 'ok', 'calls': 3, 'input_tokens': 3900,
             'output_tokens': 900, 'web_searches': 6}],
}
EMPTY = '_No data points in this window._\n'
NORMAL_REPORT = '\n'.join([
    '# SkipperCast operations report', '',
    'Requests: 1,500; 5xx: 6 (0.40 %).', '',
    '## Requests by route (last 24 h)', '',
    '| route | requests | s2xx | s3xx | s4xx | s5xx | p95_ms |\n| --- | --- | --- | --- | --- | --- | --- |\n'
    '| /feeds/* | 1,200 | 1,190 | 0 | 4 | 6 | 82 |\n| /api/om/v1/forecast | 300 | 300 | 0 | 0 | 0 | 412 |\n',
    '## LLM calls (last 24 h)', '',
    '| feature | model | outcome | calls | input_tokens | output_tokens | web_searches |\n'
    '| --- | --- | --- | --- | --- | --- | --- |\n| boat_lookup | claude-sonnet-5 | ok | 3 | 3,900 | 900 | 6 |\n',
    '## Trip-check queue batches (last 24 h)', '', EMPTY,
    '## Cron runs (last 24 h)', '', EMPTY,
    '## Client funnel (last 24 h)', '', ops_report.NOTES['funnel'], '', EMPTY,
    '## Top client errors (last 24 h)', '', EMPTY,
])


def route(name, requests, s5xx: object = 0):
    return {'route': name, 'requests': requests, 's2xx': 0, 's3xx': 0, 's4xx': 0, 's5xx': s5xx, 'p95_ms': 10}


class FiniteNumberTests(unittest.TestCase):
    def test_unreadable_numbers_render_as_a_dash(self):
        for raw in ('nan', 'inf', '-inf', 'abc', '', 'NaN', 'Infinity', '1e999', float('nan'), float('inf'), None, [], {}):
            with self.subTest(raw=raw):
                self.assertIsNone(ops_report.finite(raw))
                self.assertEqual(ops_report.cell(ops_report.number(raw)), '—')

    def test_a_bool_is_not_a_count(self):
        for raw in (True, False):
            with self.subTest(raw=raw):
                self.assertIsNone(ops_report.finite(raw))
                self.assertEqual(ops_report.cell(ops_report.number(raw)), '—')
                self.assertEqual(ops_report.line_number(raw), '—')
        text = ops_report.report({'routes': [route('/a', True, True), route('/b', 5)]}, now=NOW)
        self.assertIn('Requests: 5; 5xx: 0 (0.00 %) (2 unreadable value(s) skipped).', text)
        self.assertIn('| /a | — | 0 | 0 | 0 | — | 10 |', text)

    def test_normal_numbers_keep_their_format(self):
        self.assertEqual(ops_report.finite('1200'), 1200.0)
        self.assertEqual(ops_report.finite(7), 7.0)
        self.assertEqual(ops_report.cell(ops_report.number('1200')), '1,200')
        self.assertEqual(ops_report.cell(ops_report.number(2.5)), '2.5')
        self.assertEqual(ops_report.cell(ops_report.number('0')), '0')

    def test_line_number(self):
        for raw in ('inf', 'nan', '-inf', 'x', None):
            with self.subTest(raw=raw):
                self.assertEqual(ops_report.line_number(raw), '—')
        self.assertEqual(ops_report.line_number('42.0'), '42')
        self.assertEqual(ops_report.line_number(120.0), '120')
        rows = [{'message': 'm', 'source': 's', 'line': 'inf', 'kind': 'error', 'build': 'b', 'reports': 'nan'}]
        text = ops_report.report({'client_errors': rows}, now=NOW)
        self.assertIn('| `m` | `s` | — | error | b | — |', text)

    def test_unreadable_requests_are_skipped_from_the_totals_and_counted(self):
        routes = [route('/nan', 'nan'), route('/x', 'x'), route('/ok', '100', '4')]
        text = ops_report.report({'routes': routes}, now=NOW)
        self.assertIn('Requests: 100; 5xx: 4 (4.00 %) (2 unreadable value(s) skipped).', text)
        self.assertIn('| /nan | — | 0 | 0 | 0 | 0 | 10 |', text)
        self.assertIn('| /x | — | 0 | 0 | 0 | 0 | 10 |', text)
        self.assertNotIn('nan', text.replace('/nan', ''))
        # An unreadable 5xx count is skipped too; a missing (None) cell is not "unreadable".
        text = ops_report.report({'routes': [route('/a', 50, 'inf'), route('/b', None, None), route('/c', 50, 1)]}, now=NOW)
        self.assertIn('Requests: 100; 5xx: 1 (1.00 %) (1 unreadable value(s) skipped).', text)

    def test_all_requests_unreadable_gives_zero_without_dividing(self):
        routes = [route('/a', 'nan', 'nan'), route('/b', '-inf', 'oops'), route('/c', '', 3)]
        text = ops_report.report({'routes': routes}, now=NOW)
        self.assertIn('Requests: 0; 5xx: 3 (0.00 %) (5 unreadable value(s) skipped).', text)

    def test_fleet_line_with_unreadable_heartbeat_or_messages(self):
        row = {'region': 'CA', 'pushed_at': '2026-10-05 09:00:00', 'heartbeat_age_s': 'inf', 'last_message_age_s': 1,
               'messages_24h': 'nan'}
        self.assertEqual(ops_report.fleet_line([row], '', NOW),
                         'Fleet AIS: listener heartbeat age unknown; no open fleet-ais-stale issue.')
        for beat, messages in (('nan', '-inf'), ('-5', '-1'), (True, True), ('x', 'y')):
            with self.subTest(beat=beat, messages=messages):
                line = ops_report.fleet_line([dict(row, heartbeat_age_s=beat, messages_24h=messages)], '#3', NOW)
                self.assertEqual(line, 'Fleet AIS: listener heartbeat age unknown; open fleet-ais-stale issue #3.')
        line = ops_report.fleet_line([dict(row, heartbeat_age_s='1800', messages_24h='512000')], '', NOW)
        self.assertEqual(line, 'Fleet AIS: listener heartbeat 1.5 h old; 512,000 AIS rows stored in 24 h; '
                               'no open fleet-ais-stale issue.')

    def test_funnel_with_an_unreadable_count_renders_a_dash(self):
        text = ops_report.report({'funnel': [{'event': 'map_viewed', 'events': 'nan'}, {'event': 'install', 'events': '3'}]},
                                 now=NOW)
        self.assertIn('| map_viewed | — |', text)
        self.assertIn('| install | 3 |', text)

    def test_a_normal_fixture_renders_exactly_as_before(self):
        self.assertEqual(ops_report.report(NORMAL, now=NOW), NORMAL_REPORT)


if __name__ == '__main__':
    unittest.main()

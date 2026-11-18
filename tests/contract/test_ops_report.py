"""scripts/ops_report.py: Analytics Engine SQL queries and the Markdown report, offline."""
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from scripts import ops_report
from tests._support import ROOT


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(answers, seen):
    def opener(request, timeout):
        sql = request.data.decode()
        seen.append((request.full_url, request.get_header('Authorization'), sql))
        for key, rows in answers.items():
            if f"index1 = '{key}'" in sql:
                if isinstance(rows, Exception):
                    raise rows
                return FakeResponse(json.dumps({'meta': [], 'data': rows, 'rows': len(rows)}).encode())
        return FakeResponse(b'{"data": []}')
    return opener


def run(argv, env, opener):
    with redirect_stdout(io.StringIO()):
        return ops_report.main(argv, env, opener=opener)


ENV = {'CF_ANALYTICS_TOKEN': 'token-value', 'CLOUDFLARE_ACCOUNT_ID': 'acct123'}


class OpsReportTests(unittest.TestCase):
    def test_skips_cleanly_without_a_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            calls = []
            self.assertEqual(run([], {'GITHUB_STEP_SUMMARY': str(summary)}, opener_for({}, calls)), 0)
            self.assertEqual(calls, [])
            self.assertIn('skipped', summary.read_text())
            self.assertIn('batched reads unknown; configured ceiling unknown; headroom unknown', summary.read_text())

    def test_queries_the_dataset_for_the_last_day_with_bearer_auth(self):
        seen = []
        self.assertEqual(run([], dict(ENV), opener_for({}, seen)), 0)
        self.assertEqual(len(seen), len(ops_report.QUERIES))
        for url, auth, sql in seen:
            self.assertEqual(url, 'https://api.cloudflare.com/client/v4/accounts/acct123/analytics_engine/sql')
            self.assertEqual(auth, 'Bearer token-value')
            self.assertIn('FROM skippercast_events', sql)
            self.assertIn("timestamp > NOW() - INTERVAL '1' DAY", sql)
        routes = next(sql for _, _, sql in seen if "index1 = 'request'" in sql)
        self.assertIn('quantileExactWeighted(0.95)(double2, _sample_interval)', routes)
        self.assertIn('_sample_interval * double3', routes, 'sampled feed reads are weighted back up')

    def test_report_is_a_markdown_table_with_totals(self):
        answers = {'request': [
            {'route': '/feeds/*', 'requests': '1200', 's2xx': '1190', 's3xx': '0', 's4xx': '4', 's5xx': '6', 'p95_ms': 81.5},
            {'route': '/api/om/v1/forecast', 'requests': 300, 's2xx': 300, 's3xx': 0, 's4xx': 0, 's5xx': 0, 'p95_ms': 412.25}],
            'llm': [{'feature': 'boat_lookup', 'model': 'claude-sonnet-5', 'outcome': 'ok', 'calls': 3, 'input_tokens': 3900, 'output_tokens': 900, 'web_searches': 6}]}
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            env = dict(ENV, GITHUB_STEP_SUMMARY=str(summary))
            self.assertEqual(run([], env, opener_for(answers, [])), 0)
            text = summary.read_text()
        self.assertIn('Requests: 1,500; 5xx: 6 (0.40 %).', text)
        self.assertIn('| route | requests | s2xx | s3xx | s4xx | s5xx | p95_ms |', text)
        self.assertIn('| /feeds/* | 1,200 | 1,190 | 0 | 4 | 6 | 82 |', text)
        self.assertIn('| boat_lookup | claude-sonnet-5 | ok | 3 | 3,900 | 900 | 6 |', text)
        self.assertIn('## Cron runs (last 24 h)', text)
        self.assertIn('_No data points in this window._', text)
        self.assertIn('batched reads unknown; configured ceiling unknown; headroom unknown', text)
        self.assertIn('degraded duration unknown', text)

    def test_local_r2_meter_reports_utc_headroom_without_querying_or_writing_summary(self):
        # The operator is still on October 4 locally, while the meter has rolled to October 5 UTC.
        now = datetime(2026, 10, 4, 18, tzinfo=timezone(-timedelta(hours=7)))
        seen = []
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as stdout:
            summary = Path(tmp) / 'summary.md'
            env = dict(ENV, GITHUB_STEP_SUMMARY=str(summary), GITHUB_REPOSITORY='example/skippercast')
            self.assertEqual(ops_report.main(
                ['--r2-meter', '2026-10-05', '249400', '250000'], env,
                opener=opener_for({}, seen), github_opener=opener_for({}, seen), now=now,
            ), 0)
            self.assertFalse(summary.exists(), 'operator-supplied counts stay local')
        self.assertEqual(seen, [])
        text = stdout.getvalue()
        self.assertIn('2026-10-05 UTC', text)
        self.assertIn('249,400 batched reads; configured ceiling 250,000; 600 reads of recorded headroom', text)
        self.assertIn('may omit pending reads', text)
        self.assertIn('degraded duration unknown', text)

    def test_local_r2_meter_keeps_unknown_inputs_distinct_from_measured_zero(self):
        now = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
        cases = [
            (('2026-10-04', '299400', '300000'), 'batched reads unknown; configured ceiling unknown; headroom unknown'),
            (('2026-10-05', 'NaN', '300000'), 'batched reads unknown; configured ceiling 300,000; headroom unknown'),
            (('2026-10-05', '299400', 'unknown'), '299,400 batched reads; configured ceiling unknown; headroom unknown'),
            (('2026-10-05', '299400', 'off'), '299,400 batched reads; configured ceiling off; headroom not applicable'),
            (('2026-10-05', '0', '300000'), '0 batched reads; configured ceiling 300,000; 300,000 reads of recorded headroom'),
            (('2026-10-05', '300001', '300000'), '300,001 batched reads; configured ceiling 300,000; headroom exhausted (1 over ceiling)'),
        ]
        for meter, expected in cases:
            with self.subTest(meter=meter), redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(ops_report.main(['--r2-meter', *meter], {}, now=now), 0)
                self.assertIn(expected, stdout.getvalue())
                self.assertIn('degraded duration unknown', stdout.getvalue())

    def test_report_shows_the_client_funnel_in_order_and_the_top_client_errors(self):
        answers = {
            'client_event': [{'event': 'map_viewed', 'events': '40'}, {'event': 'port_selected', 'events': 50},
                             {'event': 'forecast_viewed', 'events': 12}],
            'client_error': [{'message': 'TypeError: a | b <img>', 'source': 'index.0123456789.js', 'line': 120.0,
                              'kind': 'error', 'build': '0123456789', 'reports': '7'}],
        }
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            self.assertEqual(run([], dict(ENV, GITHUB_STEP_SUMMARY=str(summary)), opener_for(answers, seen)), 0)
            text = summary.read_text()
        funnel = next(sql for _, _, sql in seen if "index1 = 'client_event'" in sql)
        self.assertIn('SUM(_sample_interval) AS events', funnel)
        errors = next(sql for _, _, sql in seen if "index1 = 'client_error'" in sql)
        self.assertIn('ORDER BY reports DESC LIMIT 10', errors)
        self.assertIn('## Client funnel (last 24 h)', text)
        self.assertIn('not per person', text)
        steps = text.index('| port_selected | 50 |'), text.index('| map_viewed | 40 |'), text.index('| forecast_viewed | 12 |'), text.index('| spot_saved | 0 |')
        self.assertEqual(list(steps), sorted(steps), 'funnel steps are listed in visit order')
        self.assertIn('## Top client errors (last 24 h)', text)
        self.assertIn('| `TypeError: a \\| b <img>` | `index.0123456789.js` | 120 | error | 0123456789 | 7 |', text)

    def test_browser_supplied_text_cannot_forge_links_images_or_code(self):
        forged = '[Reset your token](https://evil.example/x) ![p](https://evil.example/p.png) `x` <script>'
        rows = [{'message': forged, 'source': '`](https://evil.example)', 'line': 1, 'kind': 'error', 'build': 'dev', 'reports': 1}]
        text = ops_report.table(rows)
        row = text.splitlines()[2]
        cells = [c.strip() for c in row.strip('|').split(' | ')]
        self.assertEqual(cells[0], '`[Reset your token](https://evil.example/x) ![p](https://evil.example/p.png) x <script>`')
        self.assertEqual(cells[1], '`](https://evil.example)`')
        for value in cells[:2]:
            self.assertTrue(value.startswith('`') and value.endswith('`'))
            self.assertNotIn('`', value[1:-1], 'no backtick can close the code span early')
        self.assertEqual(ops_report.code_cell(''), '—')

    def test_api_errors_fail_but_a_never_written_dataset_only_warns(self):
        def error(code, body):
            return HTTPError('u', code, 'err', {}, io.BytesIO(body.encode()))
        missing = {'request': error(404, 'table skippercast_events not found')}
        self.assertEqual(run([], dict(ENV), opener_for(missing, [])), 0)
        denied = {'request': error(403, 'Authentication error')}
        self.assertEqual(run([], dict(ENV), opener_for(denied, [])), 1)

    def test_fleet_ais_line_gives_heartbeat_age_messages_and_the_open_issue(self):
        answers = {'fleet_ais': [{'region': 'CA', 'pushed_at': '2026-10-05 09:00:00', 'heartbeat_age_s': '1800',
                                  'last_message_age_s': 1790, 'messages_24h': '512000'}]}
        issues = []

        def github(request, timeout):
            issues.append(request.full_url)
            return FakeResponse(json.dumps([{'number': 41, 'title': 'Fleet AIS listener or processor is stale'}]).encode())

        seen, now = [], datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            env = dict(ENV, GITHUB_STEP_SUMMARY=str(summary), GITHUB_REPOSITORY='example/skippercast')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(ops_report.main([], env, opener=opener_for(answers, seen), github_opener=github, now=now), 0)
            text = summary.read_text()
        self.assertIn('Fleet AIS: listener heartbeat 1.5 h old; 512,000 AIS rows stored in 24 h; '
                      'open fleet-ais-stale issue #41.', text)
        self.assertEqual(issues, ['https://api.github.com/repos/example/skippercast/issues?labels=fleet-ais-stale&state=open&per_page=1'])
        self.assertNotIn('fleet_ais', text, 'a line, not a table')
        # Without fleet data or an open issue there is no line at all (the fleet is off).
        self.assertIsNone(ops_report.fleet_line([], '', now))
        self.assertEqual(ops_report.fleet_line([], None, now), None)
        self.assertEqual(ops_report.fleet_line([], '#7', now), 'Fleet AIS: no processor heartbeat in 24 h; open fleet-ais-stale issue #7.')

    def test_workflow_is_daily_pinned_and_passes_the_optional_token(self):
        text = (ROOT / '.github' / 'workflows' / 'ops-report.yml').read_text()
        self.assertIn('schedule:', text)
        self.assertIn('CF_ANALYTICS_TOKEN: ${{ secrets.CF_ANALYTICS_TOKEN }}', text)
        self.assertIn('python scripts/ops_report.py', text)
        for line in text.splitlines():
            if 'uses:' in line:
                self.assertRegex(line, r'uses: [\w./-]+@[0-9a-f]{40} # v', 'actions are pinned to a commit SHA')
        self.assertIn('permissions:\n  contents: read', text)


if __name__ == '__main__':
    unittest.main()

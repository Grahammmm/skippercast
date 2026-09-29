"""scripts/ops_report.py: Analytics Engine SQL queries and the Markdown report, offline."""
import io
import json
from contextlib import redirect_stdout
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from scripts import ops_report


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

    def test_api_errors_fail_but_a_never_written_dataset_only_warns(self):
        def error(code, body):
            return HTTPError('u', code, 'err', {}, io.BytesIO(body.encode()))
        missing = {'request': error(404, 'table skippercast_events not found')}
        self.assertEqual(run([], dict(ENV), opener_for(missing, [])), 0)
        denied = {'request': error(403, 'Authentication error')}
        self.assertEqual(run([], dict(ENV), opener_for(denied, [])), 1)

    def test_workflow_is_daily_pinned_and_passes_the_optional_token(self):
        text = (Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'ops-report.yml').read_text()
        self.assertIn('schedule:', text)
        self.assertIn('CF_ANALYTICS_TOKEN: ${{ secrets.CF_ANALYTICS_TOKEN }}', text)
        self.assertIn('python scripts/ops_report.py', text)
        for line in text.splitlines():
            if 'uses:' in line:
                self.assertRegex(line, r'uses: [\w./-]+@[0-9a-f]{40} # v', 'actions are pinned to a commit SHA')
        self.assertIn('permissions:\n  contents: read', text)


if __name__ == '__main__':
    unittest.main()

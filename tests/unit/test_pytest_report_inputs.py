"""scripts/pytest_report.py: unreadable JUnit/--ci-runs files are named (exit 2); garbled test times count as 0."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import pytest_report

GOOD = '<testsuite><testcase classname="tests.unit.t.A" name="test_ok" time="0.10"/></testsuite>'
TIMES = '''<testsuite>
<testcase classname="tests.unit.t.A" name="abc" time="abc"/>
<testcase classname="tests.unit.t.A" name="not_a_number" time="nan"/>
<testcase classname="tests.unit.t.A" name="endless" time="inf"/>
<testcase classname="tests.unit.t.A" name="negative" time="-5"/>
<testcase classname="tests.unit.t.A" name="missing"/>
<testcase classname="tests.unit.t.A" name="slow" time="1.50"/>
<testcase classname="tests.unit.t.A" name="fast" time="0.25"/>
</testsuite>'''
RUN = {'databaseId': 1, 'createdAt': '2026-11-01T10:00:00Z', 'updatedAt': '2026-11-01T10:05:00Z',
       'status': 'completed', 'conclusion': 'success',
       'jobs': [{'name': 'check', 'status': 'completed', 'conclusion': 'success',
                 'startedAt': '2026-11-01T10:00:10Z', 'completedAt': '2026-11-01T10:04:00Z'}]}


class PytestReportInputsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pytest_report.main([str(arg) for arg in argv])
        return code, out.getvalue(), err.getvalue()

    def assert_refused(self, argv, path, reason):
        code, out, err = self.run_main(*argv)
        self.assertEqual(code, 2)
        self.assertEqual(err, f'pytest_report: {path}: {reason}\n')
        self.assertEqual(out, '')

    def test_unreadable_junit_is_named_with_no_table(self):
        good = self.write('good.xml', GOOD)
        for path in (self.root / 'missing.xml', self.write('empty.xml', ''),
                     self.write('truncated.xml', '<testsuite><testcase'), self.root):
            with self.subTest(path=path.name):
                self.assert_refused([path], path, 'unreadable JUnit XML')
                self.assert_refused([good, path], path, 'unreadable JUnit XML')

    def test_garbled_times_count_as_zero_with_a_count_line(self):
        rows = list(pytest_report.cases([self.write('times.xml', TIMES)]))
        times = {row['id'].split('::')[1]: row['time'] for row in rows}
        self.assertEqual(times, {'abc': 0.0, 'not_a_number': 0.0, 'endless': 0.0, 'negative': 0.0, 'missing': 0.0,
                                 'slow': 1.5, 'fast': 0.25})
        self.assertEqual([row['id'].split('::')[1] for row in rows if row['time_unreadable']],
                         ['abc', 'not_a_number', 'endless', 'negative'])
        text = pytest_report.report(rows, 'T', slowest=3)
        self.assertIn('\n4 test time(s) unreadable; counted as 0 s\n', text)
        self.assertIn('7 tests: 7 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed; 1.8 s in tests', text)
        self.assertIn('| unit | 7 | 0 | 0 | 1.8 |', text)
        self.assertNotIn('nan', text)
        self.assertNotIn('inf', text)
        slowest = text.split('Slowest 3:\n\n')[1].splitlines()
        self.assertEqual(slowest[:2], ['- 1.50 s `tests.unit.t.A::slow`', '- 0.25 s `tests.unit.t.A::fast`'])
        self.assertTrue(slowest[2].startswith('- 0.00 s '))
        code, out, _ = self.run_main(self.root / 'times.xml')
        self.assertEqual(code, 0)
        self.assertIn('4 test time(s) unreadable; counted as 0 s', out)

    def test_readable_times_have_no_count_line(self):
        code, out, _ = self.run_main(self.write('good.xml', GOOD))
        self.assertEqual(code, 0)
        self.assertNotIn('unreadable', out)

    def test_unreadable_ci_runs_are_named(self):
        latin = self.root / 'latin.json'
        latin.write_bytes(b'["\xff"]')
        cases = [(self.root / 'missing.json', 'unreadable JSON'),
                 (self.write('bad.json', '[{"databaseId": '), 'unreadable JSON'),
                 (self.write('deep.json', '[' * 100000 + ']' * 100000), 'unreadable JSON'),
                 (latin, 'unreadable JSON'),
                 (self.write('dict.json', '{}'), 'expected a JSON list of run objects'),
                 (self.write('ints.json', '[1]'), 'expected a JSON list of run objects'),
                 (self.write('mixed.json', json.dumps([RUN, 'x'])), 'expected a JSON list of run objects')]
        for path, reason in cases:
            with self.subTest(path=path.name):
                self.assert_refused(['--ci-runs', path], path, reason)

    def test_incomplete_run_receipts_hold_without_traceback(self):
        no_jobs = {key: value for key, value in RUN.items() if key != 'jobs'} | {'databaseId': 2}
        bad_date = RUN | {'databaseId': 3, 'createdAt': 'yesterday'}
        bad_job = RUN | {'databaseId': 4, 'jobs': [{'name': 'check', 'conclusion': 'success'}]}
        bad_job_date = RUN | {'databaseId': 5, 'jobs': [RUN['jobs'][0] | {'completedAt': 'soon'}]}
        naive = RUN | {'databaseId': 6, 'createdAt': '2026-11-01T10:00:00'}
        self.assertEqual(self.run_main('--ci-runs', self.write('ok.json', json.dumps([RUN])))[0], 0)
        for runs in ([no_jobs, bad_date], [RUN, no_jobs], [RUN, bad_date], [RUN, bad_job],
                     [RUN, bad_job_date], [RUN, naive], [{}]):
            with self.subTest(ids=[run.get('databaseId') for run in runs]):
                code, out, err = self.run_main('--ci-runs', self.write('runs.json', json.dumps(runs)))
                self.assertEqual(code, 1)
                self.assertEqual(err, '')
                self.assertRegex(out, r'\| \*\*Total\*\* \|[^\n]*\| HOLD \|')
                self.assertIn('incomplete receipt', out)
                self.assertIn('BLOCK further feature admission', out)

    def test_duplicate_run_receipt_still_refused(self):
        with self.assertRaisesRegex(ValueError, 'duplicate run receipt'):
            pytest_report.ci_budget([RUN, RUN])


if __name__ == '__main__':
    unittest.main()

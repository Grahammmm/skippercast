"""scripts/pytest_report.py: JUnit summary for CI and the survey job's skip allowlist."""
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from scripts import pytest_report

JUNIT = '''<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="5">
<testcase classname="tests.unit.test_a.A" name="test_ok" time="0.10"/>
<testcase classname="tests.gis.test_b.B" name="test_private" time="0.00">
  <skipped type="pytest.skip" message="Private reference grid absent; committed ledger tested separately"/>
</testcase>
<testcase classname="research.tests.gis.test_c.C" name="test_missing_package" time="0.00">
  <skipped type="pytest.skip" message="Optional GRIB decoder not installed"/>
</testcase>
<testcase classname="research.tests.test_d.D" name="test_fails" time="2.50"><failure message="boom"/></testcase>
<testcase classname="tests.contract.test_e.E" name="test_errors" time="0.20"><error message="bad"/></testcase>
</testsuite></testsuites>'''


class PytestReportTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'junit.xml'
        self.path.write_text(JUNIT)
        self.rows = list(pytest_report.cases([self.path]))

    def tearDown(self):
        self.directory.cleanup()

    def test_outcomes_and_layers(self):
        self.assertEqual([(r['layer'], r['outcome']) for r in self.rows],
                         [('unit', 'passed'), ('gis', 'skipped'), ('claims (gis)', 'skipped'),
                          ('claims', 'failed'), ('contract', 'error')])
        text = pytest_report.report(self.rows, 'T', slowest=1)
        self.assertIn('5 tests: 1 passed, 1 failed, 1 errors, 2 skipped', text)
        self.assertIn('| claims (gis) | 1 | 1 |', text)
        self.assertIn('2.50 s `research.tests.test_d.D::test_fails`', text)

    def test_only_allow_listed_private_cache_skips_pass(self):
        bad = pytest_report.unexpected_skips(self.rows)
        self.assertEqual([r['reason'] for r in bad], ['Optional GRIB decoder not installed'])
        with open(Path(self.directory.name) / 'out.txt', 'w') as out, unittest.mock.patch('sys.stdout', out), \
                unittest.mock.patch('sys.stderr', out):
            self.assertEqual(pytest_report.main([str(self.path), '--strict-skips']), 1)
            self.assertEqual(pytest_report.main([str(self.path)]), 0)


if __name__ == '__main__':
    unittest.main()

"""scripts/pytest_report.py refuses well-formed XML whose root is not testsuite/testsuites (exit 2, no table)."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts import pytest_report

CASE = '<testcase classname="tests.unit.t.A" name="test_ok" time="0.10"/>'
SUITE = f'<testsuite>{CASE}</testsuite>'
SUITES = f'<testsuites><testsuite>{CASE}</testsuite><testsuite>{CASE.replace("test_ok", "test_two")}</testsuite></testsuites>'


class JunitRootTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pytest_report.main([str(arg) for arg in argv])
        return code, out.getvalue(), err.getvalue()

    def assert_refused(self, *paths):
        code, out, err = self.run_main(*paths, '--strict-skips')
        self.assertEqual(code, 2)
        self.assertEqual(err, f'pytest_report: {paths[-1]}: unreadable JUnit XML\n')
        self.assertEqual(out, '')

    def test_non_junit_root_is_named_unreadable(self):
        self.assert_refused(self.write('bad.xml', '<not-junit><record>synthetic</record></not-junit>'))

    def test_nested_testcase_cannot_rescue_wrong_root(self):
        self.assert_refused(self.write('bad.xml', f'<wrapper>{CASE}</wrapper>'))

    def test_valid_then_invalid_emits_no_partial_table(self):
        self.assert_refused(self.write('good.xml', SUITE), self.write('bad.xml', '<not-junit/>'))

    def test_single_and_multi_suite_controls(self):
        for name, text, count in (('one', SUITE, 1), ('many', SUITES, 2)):
            with self.subTest(name):
                code, out, err = self.run_main(self.write(name + '.xml', text))
                self.assertEqual((code, err), (0, ''))
                self.assertIn(f'{count} tests: {count} passed', out)

    def test_empty_junit_roots_remain_valid(self):
        for name, text in (('suite', '<testsuite/>'), ('suites', '<testsuites/>')):
            with self.subTest(name):
                code, out, err = self.run_main(self.write(name + '.xml', text))
                self.assertEqual((code, err), (0, ''))
                self.assertIn('0 tests: 0 passed', out)


if __name__ == '__main__':
    unittest.main()

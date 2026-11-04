"""scripts/pytest_report.py: JUnit summary for CI and the survey job's skip allowlist."""
import subprocess
import sys
import tempfile
import textwrap
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

ALLOWED = 'Private reference grid absent; committed ledger tested separately'


def suite(*cases):
    return '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">' + ''.join(cases) + '</testsuite></testsuites>'


def case(name, body='', classname='tests.unit.test_x.X', time='0.10'):
    return f'<testcase classname="{classname}" name="{name}" time="{time}">{body}</testcase>'


def skipped(message, kind='pytest.skip'):
    attr = f' type="{kind}"' if kind is not None else ''
    return f'<skipped{attr} message="{message}"/>'


class PytestReportTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'junit.xml'
        self.path.write_text(JUNIT)
        self.rows = list(pytest_report.cases([self.path]))

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, text):
        path = Path(self.directory.name) / name
        path.write_text(text)
        return path

    def strict(self, *paths):
        """Run the CLI with --strict-skips; returns (exit code, stdout, stderr)."""
        out, err = Path(self.directory.name) / 'o.txt', Path(self.directory.name) / 'e.txt'
        with open(out, 'w') as o, open(err, 'w') as e, unittest.mock.patch('sys.stdout', o), \
                unittest.mock.patch('sys.stderr', e):
            code = pytest_report.main([*map(str, paths), '--strict-skips'])
        return code, out.read_text(), err.read_text()

    def outcomes(self, *cases_):
        return [(r['outcome'], r['reason']) for r in pytest_report.cases([self.write('c.xml', suite(*cases_))])]

    def test_outcomes_and_layers(self):
        self.assertEqual([(r['layer'], r['outcome']) for r in self.rows],
                         [('unit', 'passed'), ('gis', 'skipped'), ('claims (gis)', 'skipped'),
                          ('claims', 'failed'), ('contract', 'error')])
        text = pytest_report.report(self.rows, 'T', slowest=1)
        self.assertIn('5 tests: 1 passed, 1 failed, 1 errors, 2 skipped, 0 xfailed', text)
        self.assertIn('| Layer | Tests | Skipped | Xfailed | Time (s) |', text)
        self.assertIn('| claims (gis) | 1 | 1 | 0 |', text)
        self.assertIn('2.50 s `research.tests.test_d.D::test_fails`', text)

    def test_only_allow_listed_private_cache_skips_pass(self):
        bad = pytest_report.unexpected_skips(self.rows)
        self.assertEqual([r['reason'] for r in bad], ['Optional GRIB decoder not installed'])
        with open(Path(self.directory.name) / 'out.txt', 'w') as out, unittest.mock.patch('sys.stdout', out), \
                unittest.mock.patch('sys.stderr', out):
            self.assertEqual(pytest_report.main([str(self.path), '--strict-skips']), 1)
            self.assertEqual(pytest_report.main([str(self.path)]), 0)

    def test_exact_xfail_type_is_its_own_outcome_with_reason(self):
        got = self.outcomes(case('a', skipped('SC-FLAKE-PGID pending', 'pytest.xfail')),
                            case('b', skipped('  ', 'pytest.xfail')),
                            case('c', '<skipped type="pytest.xfail"/>'))
        self.assertEqual(got, [('xfailed', 'SC-FLAKE-PGID pending'), ('xfailed', ''), ('xfailed', '')])

    def test_only_the_exact_type_makes_an_xfail(self):
        # a reason that says xfail, or a lookalike/missing type, is still an ordinary skip
        got = self.outcomes(case('a', skipped('xfail: expected', 'pytest.skip')),
                            case('b', skipped('expected failure', 'pytest.xfail.strict')),
                            case('c', skipped('expected failure', 'xfail')),
                            case('d', skipped('expected failure', 'PYTEST.XFAIL')),
                            case('e', skipped('expected failure', None)))
        self.assertEqual({outcome for outcome, _ in got}, {'skipped'})
        rows = list(pytest_report.cases([self.path.with_name('c.xml')]))
        self.assertEqual(len(pytest_report.unexpected_skips(rows)), 5)

    def test_xfail_is_counted_in_headline_and_layer_table_once(self):
        xml = suite(case('ok'),
                    case('x1', skipped('r', 'pytest.xfail')),
                    case('x2', skipped('r', 'pytest.xfail'), classname='tests.gis.test_g.G'),
                    case('x3', skipped('r', 'pytest.xfail'), classname='tests.gis.test_g.G'),
                    case('s', skipped(ALLOWED), classname='tests.gis.test_g.G'),
                    case('f', '<failure message="boom"/>', classname='research.tests.test_d.D'),
                    case('e', '<error message="bad"/>', classname='tests.contract.test_e.E'))
        other = suite(case('x4', skipped('r', 'pytest.xfail'), classname='odd.module.M'),
                      case('u', skipped('Optional GRIB decoder not installed'), classname='odd.module.M'))
        rows = [*pytest_report.cases([self.write('a.xml', xml)]), *pytest_report.cases([self.write('b.xml', other)])]
        text = pytest_report.report(rows, 'T')
        self.assertIn('9 tests: 1 passed, 1 failed, 1 errors, 2 skipped, 4 xfailed', text)
        self.assertIn('| unit | 2 | 0 | 1 |', text)
        self.assertIn('| gis | 3 | 1 | 2 |', text)
        self.assertIn('| claims | 1 | 0 | 0 |', text)
        self.assertIn('| contract | 1 | 0 | 0 |', text)
        self.assertIn('| other | 2 | 1 | 1 |', text)
        # per-layer columns reconcile with the headline
        table = [line.split('|') for line in text.splitlines() if line.startswith('| ') and 'Layer' not in line
                 and '---' not in line]
        self.assertEqual(sum(int(c[2]) for c in table), 9)
        self.assertEqual(sum(int(c[3]) for c in table), 2)
        self.assertEqual(sum(int(c[4]) for c in table), 4)

    def test_failure_and_error_outrank_a_skipped_child_in_either_order(self):
        for tag in ('failure', 'error'):
            for first_skip in (True, False):
                for kind in ('pytest.xfail', 'pytest.skip'):
                    parts = [skipped(ALLOWED, kind), f'<{tag} message="m"/>']
                    got = self.outcomes(case('t', ''.join(parts if first_skip else parts[::-1])))
                    self.assertEqual([o for o, _ in got], ['failed' if tag == 'failure' else 'error'],
                                     (tag, first_skip, kind))

    def test_xfail_only_report_passes_strict_with_nothing_allow_listed(self):
        path = self.write('x.xml', suite(*(case(f't{i}', skipped('SC-FLAKE-PGID', 'pytest.xfail')) for i in range(5))))
        code, out, err = self.strict(path)
        self.assertEqual(code, 0, err)
        self.assertIn('5 tests: 0 passed, 0 failed, 0 errors, 0 skipped, 5 xfailed', out)
        self.assertIn('No unexpected skips (0 allow-listed private-cache skips)', out)
        self.assertEqual(err, '')

    def test_unknown_skip_among_xfails_still_fails_and_names_only_the_skip(self):
        path = self.write('m.xml', suite(case('good', skipped('r', 'pytest.xfail')),
                                         case('bad', skipped('Optional GRIB decoder not installed')),
                                         case('ok', skipped(ALLOWED))))
        code, out, err = self.strict(path)
        self.assertEqual(code, 1)
        self.assertIn('::error::Unexpected skip in the full run: tests.unit.test_x.X::bad', err)
        self.assertNotIn('X::good', err)
        self.assertNotIn('X::ok', err)
        self.assertIn('**1 unexpected skip(s)**', out)

    def test_xfail_message_cannot_borrow_an_allow_listed_reason(self):
        # an allow-listed reason on a plain skip stays allowed; an unknown reason is not exempted by xfail text
        ok = self.write('ok.xml', suite(case('a', skipped(ALLOWED))))
        self.assertEqual(self.strict(ok)[0], 0)
        bad = self.write('bad.xml', suite(case('a', skipped('xfail: ' + ALLOWED))))
        self.assertEqual(self.strict(bad)[0], 1)

    def test_empty_report_is_strict_clean(self):
        code, out, err = self.strict(self.write('e.xml', suite()))
        self.assertEqual((code, err), (0, ''))
        self.assertIn('0 tests: 0 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed', out)

    def test_failure_messages_are_not_reinterpreted(self):
        got = self.outcomes(case('a', '<failure message="[XPASS(strict)] reason"/>'),
                            case('b', '<failure message="XFAIL"/>'))
        self.assertEqual([o for o, _ in got], ['failed', 'failed'])

    def test_real_pytest_strict_xfail_and_xpass_serialisation(self):
        """An isolated pytest run: strict XFAIL is an xfail row; strict XPASS is a failure pytest itself exits 1 for."""
        project = Path(self.directory.name) / 'iso'
        project.mkdir()
        (project / 'test_iso.py').write_text(textwrap.dedent('''
            import pytest

            @pytest.mark.xfail(strict=True, reason='expected to fail')
            def test_expected_failure():
                assert False

            @pytest.mark.xfail(strict=True, reason='expected to fail')
            def test_unexpected_pass():
                assert True
        '''))
        junit = project / 'iso.xml'
        run = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider', '-p', 'no:xdist',
                              '--rootdir', str(project), '--confcutdir', str(project), '-q',
                              f'--junitxml={junit}', str(project / 'test_iso.py')],
                             cwd=project, capture_output=True, text=True, timeout=120,
                             env={'PATH': '/nonexistent', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'})
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)  # the XPASS(strict) fails pytest itself
        rows = {row['id'].rsplit('::', 1)[1]: row for row in pytest_report.cases([junit])}
        self.assertEqual(rows['test_expected_failure']['outcome'], 'xfailed')
        self.assertEqual(rows['test_unexpected_pass']['outcome'], 'failed')
        code, out, err = self.strict(junit)
        self.assertEqual(code, 0)  # the reporter does not duplicate pytest's failure exit
        self.assertIn('2 tests: 0 passed, 1 failed, 0 errors, 0 skipped, 1 xfailed', out)


if __name__ == '__main__':
    unittest.main()

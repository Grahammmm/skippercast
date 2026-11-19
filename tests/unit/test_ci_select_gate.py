"""The survey-science roll-up gate: diagnostic CLI output versus the evidence() oracle."""
import io
import itertools
import os
from pathlib import Path
import re
import subprocess
import tempfile
from textwrap import dedent
import unittest

from scripts import ci_select
from tests._support import ROOT

EVENTS = ('pull_request', 'push', 'schedule', 'merge_group', 'workflow_dispatch')
RESULTS = ('success', 'failure', 'cancelled', 'skipped', '', 'pending')
BOOLS = ('true', 'false', '')


def run_gate(event, env, summary=None):
    out, err = io.StringIO(), io.StringIO()
    environ = dict(env)
    if summary is not None:
        environ['GITHUB_STEP_SUMMARY'] = str(summary)
    code = ci_select.gate(event, environ, out, err)
    return code, out.getvalue(), err.getvalue()


def env_of(gate='success', core='true', survey='true', web='true', check='success', tests='success'):
    return dict(GATE=gate, CORE=core, SURVEY=survey, WEB=web, CHECK=check, TESTS=tests)


class GateParityTest(unittest.TestCase):
    def test_exit_code_matches_evidence_over_the_full_cross_product(self):
        for event, gate, check, tests, survey in itertools.product(EVENTS, RESULTS, RESULTS, RESULTS, BOOLS):
            env = env_of(gate=gate, survey=survey, check=check, tests=tests)
            code, _, _ = run_gate(event, env)
            want = ci_select.evidence(event, gate, 'true', survey, 'true', check, tests)
            self.assertEqual(code, 0 if want else 1, (event, gate, check, tests, survey))

    def test_malformed_selection_and_all_false_fail_closed(self):
        for core, survey, web in (('yes', 'true', 'true'), ('true', '1', 'true'), ('true', 'true', ''),
                                  ('false', 'false', 'false')):
            code, _, err = run_gate('pull_request', env_of(core=core, survey=survey, web=web, tests='skipped'))
            self.assertEqual(code, 1, (core, survey, web))
            self.assertIn('::error::Required evidence incomplete', err)

    def test_non_pr_events_need_full_selection(self):
        for event in EVENTS[1:]:
            self.assertEqual(run_gate(event, env_of(survey='false', tests='skipped'))[0], 1, event)
            self.assertEqual(run_gate(event, env_of())[0], 0, event)

    def test_intentional_survey_skip_passes_only_for_pull_request(self):
        env = env_of(survey='false', tests='skipped')
        self.assertEqual(run_gate('pull_request', env)[0], 0)
        self.assertEqual(run_gate('pull_request', env_of(survey='false', tests='skipped', check='failure'))[0], 1)
        self.assertEqual(run_gate('pull_request', env_of(survey='true', tests='skipped'))[0], 1)


class GateDiagnosticTest(unittest.TestCase):
    def test_upstream_failure_is_named_without_error_annotation(self):
        code, out, err = run_gate('pull_request', env_of(tests='failure'))
        self.assertEqual(code, 1)
        self.assertIn('survey-tests = failure', out)
        self.assertNotIn('::error', out + err)
        self.assertEqual(err, '')

    def test_failed_changes_and_check_with_passing_science_stay_nonzero(self):
        code, out, _ = run_gate('push', env_of(gate='failure', check='cancelled'))
        self.assertEqual(code, 1)
        self.assertIn('changes = failure', out)
        self.assertIn('check = cancelled', out)

    def test_skipped_missing_or_pending_is_a_contract_error(self):
        for tests in ('skipped', '', 'pending'):
            code, out, err = run_gate('push', env_of(tests=tests))
            self.assertEqual(code, 1, tests)
            self.assertEqual(out, '')
            self.assertTrue(err.startswith('::error::Required evidence incomplete'), err)

    def test_success_prints_pass_message_and_writes_no_summary(self):
        code, out, err = run_gate('push', env_of(), summary=None)
        self.assertEqual((code, err), (0, ''))
        self.assertIn('DCO is checked independently', out)

    def test_summary_is_appended_and_sanitised(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            summary.write_text('earlier\n')
            hostile = '# pwned $(rm -rf /)\n::set-output'
            code, out, err = run_gate('pull_request', env_of(tests=hostile, check='failure'), summary=summary)
            text = summary.read_text()
        self.assertEqual(code, 1)
        self.assertTrue(text.startswith('earlier\n**survey-science: '))
        self.assertIn('`CHECK` = `failure`', text)
        self.assertIn('`TESTS` = `<invalid>`', text)
        for bad in ('pwned', 'rm -rf', 'set-output'):
            self.assertNotIn(bad, text + out + err)

    def test_summary_not_written_when_variable_absent(self):
        code, _, _ = run_gate('pull_request', env_of(tests='failure'))
        self.assertEqual(code, 1)


class WorkflowWiringTest(unittest.TestCase):
    def setUp(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.job = text.split('\n  survey-science:', 1)[1].split('\n  survey-tests:', 1)[0]
        run = self.job.split('        run: ', 1)[1]
        self.command = dedent(run[2:]) if run.startswith('|\n') else run.splitlines()[0] + '\n'

    def test_required_job_keeps_its_contract_and_truthful_step_name(self):
        self.assertIn('needs: [changes, survey-tests, check]', self.job)
        self.assertIn('if: ${{ !cancelled() }}', self.job)
        self.assertIn('TESTS: ${{ needs.survey-tests.result }}', self.job)
        self.assertRegex(self.command, re.compile(r'^python3 scripts/ci_select\.py --gate$', re.M))
        self.assertNotIn('Core suite and GIS layer passed', self.job)

    def test_workflow_requires_a_successful_full_result_even_on_no_survey_prs(self):
        # Replay the real roll-up step: the legacy CLI alone accepts an intentional
        # skip on a no-survey PR and rejects actual success for that selection.
        cases = [(env_of(core='false', survey='false', tests=result), int(result != 'success'))
                 for result in RESULTS]
        cases += [(env_of(survey=''), 1), (env_of(core='false', survey='false', web='false'), 1)]
        with tempfile.TemporaryDirectory() as tmp:
            step = Path(tmp) / 'gate.sh'
            step.write_text(self.command)
            for case, expected in cases:
                env = dict(os.environ, EVENT='pull_request', **case)
                env.pop('GITHUB_STEP_SUMMARY', None)
                result = subprocess.run(['bash', '-e', str(step)], cwd=ROOT, env=env,
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, expected, (case, result.stdout, result.stderr))


if __name__ == '__main__':
    unittest.main()

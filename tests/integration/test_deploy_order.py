"""Execute the actual pre-checkout source gate offline with synthetic main metadata."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from urllib.error import URLError
from tests._support import ROOT
from tests.integration.test_deploy_source import guard

WORKFLOW = (ROOT / '.github/workflows/deploy-cloudflare.yml').read_text()
SOURCE, DEPLOY = WORKFLOW.split('\n  deploy:', 1)
SCRIPT = textwrap.dedent(SOURCE.split("          python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0])
A, B, C = 'a' * 40, 'b' * 40, 'c' * 40
REPO = 'Grahammmm/skippercast'


def held_line(selected, current):
    return ('HELD: Offline-checks commit ' + selected + ' is no longer current main (' + current
            + '); nothing deployed; production unchanged. The deploy for current main runs when its'
            + ' own Offline checks pass.')


class DeploymentOrderTests(unittest.TestCase):
    def run_gate(self, selected=B, current=B, event='workflow_run', ref='refs/heads/main', metadata=None, error=None,
                 summary=True):
        doc = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': current}}
        calls = []
        def read(request, timeout):
            calls.append((request, timeout))
            if error:
                raise error
            import json
            return io.BytesIO(json.dumps(doc if metadata is None else metadata).encode())
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'output'
            summary_file = Path(temp) / 'summary'
            env = {'GITHUB_EVENT_NAME': event, 'GITHUB_REF': ref, 'GITHUB_REPOSITORY': REPO,
                   'GITHUB_SHA': current, 'DEPLOY_SHA': selected, 'GITHUB_OUTPUT': str(output),
                   'GITHUB_STEP_SUMMARY': str(summary_file) if summary else ''}
            stdout, stderr = io.StringIO(), io.StringIO()
            code = 0
            with patch.dict(os.environ, env), patch('urllib.request.OpenerDirector.open', side_effect=read), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    exec(compile(SCRIPT, 'workflow-source-gate', 'exec'), {'__name__': '__main__'})
                except SystemExit as stop:
                    code = stop.code
            self.summary = summary_file.read_text() if summary_file.exists() else ''
            return code, output.read_text() if output.exists() else '', stdout.getvalue(), stderr.getvalue(), calls

    def test_valid_current_source_uses_selected_ci_sha_and_no_credentials(self):
        for event in ('workflow_run', 'workflow_dispatch'):
            with self.subTest(event=event):
                code, output, stdout, stderr, calls = self.run_gate(event=event)
                self.assertEqual(code, 0, stderr)
                self.assertEqual(output, 'eligible=true\n')
                self.assertEqual(self.summary, 'Deploying `' + B + '`\n')
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0].full_url, 'https://api.github.com/repos/' + REPO + '/git/ref/heads/main')
                self.assertIsNone(calls[0][0].get_header('Authorization'))
                self.assertEqual(calls[0][1], 15)

    def test_obsolete_auto_result_uses_ci_sha_not_default_branch_context_sha(self):
        code, output, stdout, stderr, _ = self.run_gate(selected=A, current=B)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(output, 'eligible=false\nheld=' + held_line(A, B) + '\n')
        self.assertIn('::warning::' + held_line(A, B), stdout)
        self.assertNotIn('::notice::', stdout)
        self.assertEqual(self.summary, '**' + held_line(A, B) + '** Offline-checks commit: `' + A
                         + '`; current main: `' + B + '`\n')

    def test_missing_step_summary_never_changes_the_gate(self):
        for selected, eligible in ((B, 'eligible=true\n'), (A, 'eligible=false\nheld=' + held_line(A, B) + '\n')):
            with self.subTest(selected=selected):
                code, output, _, stderr, _ = self.run_gate(selected=selected, current=B, summary=False)
                self.assertEqual((code, output), (0, eligible), stderr)
                self.assertEqual(self.summary, '')

    def test_delayed_completion_and_old_retry_never_promote_after_new_source(self):
        for case in ('delayed-completion', 'old-retry'):
            writes = []
            for selected, current in [(B, B), (A, B)]:
                code, output, _, stderr, _ = self.run_gate(selected=selected, current=current)
                self.assertEqual(code, 0, stderr)
                if output == 'eligible=true\n':
                    writes.append(selected)
            with self.subTest(case=case):
                self.assertEqual(writes, [B])

    def test_pending_new_main_does_not_promote_an_older_green_ancestor(self):
        code, output, _, stderr, _ = self.run_gate(selected=B, current=C)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(output, 'eligible=false\nheld=' + held_line(B, C) + '\n')

    def test_non_main_or_stale_manual_source_fails_before_checkout(self):
        for ref, selected, current in [('refs/heads/topic', B, B), ('refs/tags/main', B, B), ('refs/heads/main', A, B)]:
            with self.subTest(ref=ref, selected=selected):
                code, output, _, stderr, calls = self.run_gate(event='workflow_dispatch', ref=ref, selected=selected, current=current)
                self.assertEqual(code, 1)
                self.assertEqual(output, '')
                self.assertIn('::error::', stderr)
                if ref != 'refs/heads/main':
                    self.assertEqual(calls, [])

    def test_bad_identity_event_or_main_metadata_holds_zero_writes(self):
        for selected, event in [('', 'workflow_run'), ('invalid', 'workflow_run'), (B, 'pull_request')]:
            with self.subTest(selected=selected, event=event):
                code, output, _, _, calls = self.run_gate(selected=selected, event=event)
                self.assertEqual(code, 1)
                self.assertEqual(output, '')
                self.assertEqual(calls, [])
        for doc in ([], {}, {'ref': 'refs/heads/main'}, {'ref': 'refs/heads/topic', 'object': {'type': 'commit', 'sha': B}},
                    {'ref': 'refs/heads/main', 'object': {'type': 'tag', 'sha': B}},
                    {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': None}},
                    {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'bad'}}):
            with self.subTest(doc=doc):
                code, output, _, _, _ = self.run_gate(metadata=doc)
                self.assertEqual(code, 1)
                self.assertEqual(output, '')

    def test_network_failures_hold_zero_writes(self):
        for error in (URLError('unavailable'), TimeoutError('timeout')):
            with self.subTest(error=error):
                code, output, _, stderr, _ = self.run_gate(error=error)
                self.assertEqual(code, 1)
                self.assertEqual(output, '')
                self.assertIn('eligibility unavailable', stderr)

    def test_main_advance_between_gate_and_ci_recheck_stops_before_dependencies(self):
        code, output, _, stderr, _ = self.run_gate(selected=B, current=B)
        self.assertEqual((code, output), (0, 'eligible=true\n'), stderr)
        reads, writes = [], []
        def metadata(path):
            reads.append(path)
            return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': C}}
        with self.assertRaises(guard.SourceError):
            guard.verify_source(REPO, 'refs/heads/main', B, metadata)
            writes.append('production')
        self.assertEqual(len(reads), 1)
        self.assertEqual(writes, [])

    def test_serialized_workflow_wiring_and_rollback_boundary(self):
        self.assertIn('group: deploy-cloudflare\n  cancel-in-progress: false', SOURCE)
        gate = SOURCE.split('\n  source:', 1)[1]
        self.assertNotIn('secrets.', gate)
        self.assertNotIn('actions/checkout', gate)
        self.assertIn('DEPLOY_SHA: ${{ github.event.workflow_run.head_sha || github.sha }}', gate)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", gate)
        self.assertIn("github.event.workflow_run.event == 'push'", gate)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", gate)
        deploy, rollback = DEPLOY.split('\n  rollback:', 1)
        self.assertIn('needs: source', deploy)
        self.assertIn("needs.source.result == 'success' && needs.source.outputs.eligible == 'true'", deploy)
        self.assertIn('ref: ${{ github.event.workflow_run.head_sha || github.sha }}', deploy)
        check = deploy.index('run: python3 scripts/check_deploy_source.py')
        check_step = deploy[deploy.rfind('      - name:', 0, check):check]
        self.assertNotIn('if:', check_step, 'all eligible deployments recheck exact CI')
        self.assertLess(check, deploy.index('- uses: actions/setup-node'))
        final = deploy.index('Recheck source immediately before production writes')
        self.assertGreater(final, deploy.index('Require a smoke-test address before deploying'))
        self.assertLess(final, deploy.index('id: deploy'))
        self.assertEqual(deploy.count('run: python3 scripts/check_deploy_source.py'), 2)
        self.assertNotIn('needs: source', rollback)
        self.assertNotIn('check_deploy_source', rollback)
        self.assertIn("inputs.action == 'rollback'", rollback)

    def test_held_job_is_visible_credential_free_and_never_deploys(self):
        held = SOURCE.split('\n  held:\n', 1)[1]
        self.assertIn('    needs: source\n', held)
        self.assertIn("if: needs.source.result == 'success' && needs.source.outputs.eligible == 'false'"
                      " && github.event_name == 'workflow_run'\n", held)
        self.assertIn('timeout-minutes: 2\n', held)
        self.assertIn('HELD: ${{ needs.source.outputs.held }}', held)
        for absent in ('secrets.', 'vars.', 'actions/checkout', 'github.token', 'WRANGLER', 'exit 1'):
            self.assertNotIn(absent, held)
        self.assertIn('held: ${{ steps.current.outputs.held }}', SOURCE)


if __name__ == '__main__':
    unittest.main()

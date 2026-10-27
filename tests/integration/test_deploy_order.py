"""Execute the deploy workflow's pre-checkout source selection and its report job offline."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from tests._support import ROOT
from tests.integration.test_deploy_source import guard

WORKFLOW = (ROOT / '.github/workflows/deploy-cloudflare.yml').read_text()
SOURCE, DEPLOY = WORKFLOW.split('\n  deploy:', 1)
SCRIPT = textwrap.dedent(SOURCE.split("          python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0])
DEPLOY_JOB, AFTER = DEPLOY.split('\n  report:', 1)
REPORT, ROLLBACK = AFTER.split('\n  rollback:', 1)
REPORT_SCRIPT = textwrap.dedent(REPORT.split("          python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0])
REPO = 'Grahammmm/skippercast'
# Main's first-parent chain, newest first: E (head) <- D <- C <- B <- A. D merges topic commit T.
A, B, C, D, E, T = ('a' * 40, 'b' * 40, 'c' * 40, 'd' * 40, 'e' * 40, 'f' * 40)


def commit(sha, *parents):
    return {'sha': sha, 'parents': [{'sha': p} for p in parents]}


HISTORY = [commit(E, D), commit(D, C, T), commit(T, C), commit(C, B), commit(B, A), commit(A)]


def run(sha, run_id, status='completed', conclusion='success', **extra):
    return {'id': run_id, 'name': 'Offline checks', 'path': '.github/workflows/ci.yml', 'event': 'push',
            'head_branch': 'main', 'head_sha': sha, 'head_repository': {'full_name': REPO},
            'status': status, 'conclusion': conclusion, **extra}


class SourceSelectionTests(unittest.TestCase):
    def run_gate(self, runs, head=E, history=None, trigger=None, event='workflow_run', ref='refs/heads/main',
                 main=None, error=None):
        """runs maps a commit to its push/main Offline checks runs (or a raw listing); a missing commit has none."""
        calls = []
        def respond(request, timeout):
            calls.append((request, timeout))
            if error:
                raise error
            url = urlsplit(request.full_url)
            if url.path.endswith('/git/ref/heads/main'):
                doc = main if main is not None else {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': head}}
            elif url.path.endswith('/commits'):
                self.assertEqual(parse_qs(url.query)['sha'], [head])
                doc = HISTORY if history is None else history
            elif url.path.endswith('/actions/workflows/ci.yml/runs'):
                query = parse_qs(url.query)
                self.assertEqual((query['event'], query['branch']), (['push'], ['main']))
                found = runs.get(query['head_sha'][0], [])
                doc = found if isinstance(found, dict) else {'total_count': len(found), 'workflow_runs': found}
            else:
                raise AssertionError('unexpected metadata read ' + request.full_url)
            return io.BytesIO(json.dumps(doc).encode())
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'output'
            env = {'GITHUB_EVENT_NAME': event, 'GITHUB_REF': ref, 'GITHUB_REPOSITORY': REPO,
                   'GITHUB_SHA': head, 'TRIGGER_SHA': head if trigger is None else trigger, 'GITHUB_OUTPUT': str(output)}
            stdout, stderr = io.StringIO(), io.StringIO()
            code = 0
            with patch.dict(os.environ, env), patch('urllib.request.OpenerDirector.open', side_effect=respond), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    exec(compile(SCRIPT, 'workflow-source-gate', 'exec'), {'__name__': '__main__'})
                except SystemExit as stop:
                    code = stop.code
            text = output.read_text() if output.exists() else ''
            outputs = dict(line.split('=', 1) for line in text.splitlines())
            return code, outputs, stdout.getvalue(), stderr.getvalue(), calls

    def test_green_head_is_selected_without_credentials(self):
        for event in ('workflow_run', 'workflow_dispatch'):
            with self.subTest(event=event):
                code, out, stdout, stderr, calls = self.run_gate({E: [run(E, 9)]}, event=event)
                self.assertEqual(code, 0, stderr)
                self.assertEqual((out['eligible'], out['sha']), ('true', E))
                self.assertEqual(calls[0][0].full_url, 'https://api.github.com/repos/' + REPO + '/git/ref/heads/main')
                self.assertTrue(all(request.get_header('Authorization') is None and timeout == 15 for request, timeout in calls))
                self.assertIn('Selected for deployment: ' + E, stdout)

    def test_pending_newer_main_deploys_the_newest_checked_ancestor(self):
        # The starvation case: CI for C passed after D and E merged; D's and E's CI still run.
        code, out, _, stderr, _ = self.run_gate({E: [run(E, 12, 'in_progress', None)], D: [run(D, 11, 'queued', None)],
                                                 C: [run(C, 10)], B: [run(B, 9)]}, trigger=C)
        self.assertEqual(code, 0, stderr)
        self.assertEqual((out['eligible'], out['sha']), ('true', C))
        self.assertIn('eeeeeeeee pending', out['reason'])
        self.assertIn('ddddddddd pending', out['reason'])

    def test_failed_newer_commit_is_never_selected_and_an_older_green_one_is(self):
        code, out, _, stderr, _ = self.run_gate({E: [run(E, 12, conclusion='failure')], D: [run(D, 11, conclusion='cancelled')],
                                                 C: [run(C, 10)]})
        self.assertEqual(code, 0, stderr)
        self.assertEqual(out['sha'], C)
        self.assertIn('eeeeeeeee failure', out['reason'])

    def test_a_newer_failed_or_pending_rerun_hides_an_older_success(self):
        for status, conclusion in [('completed', 'failure'), ('in_progress', None), ('queued', None)]:
            with self.subTest(status=status):
                runs = {E: [run(E, 20, status, conclusion), run(E, 12)], D: [run(D, 11)]}
                code, out, _, stderr, _ = self.run_gate(runs)
                self.assertEqual(code, 0, stderr)
                self.assertEqual(out['sha'], D)
        # A newer success after an older failure counts.
        self.assertEqual(self.run_gate({E: [run(E, 12, conclusion='failure'), run(E, 20)]})[1]['sha'], E)

    def test_wrong_provenance_runs_are_not_success(self):
        for key, value in [('path', '.github/workflows/other.yml'), ('name', 'Other'), ('event', 'pull_request'),
                           ('head_branch', 'topic'), ('head_sha', T), ('head_repository', {'full_name': 'x/y'}),
                           ('head_repository', None)]:
            with self.subTest(key=key):
                bad = run(E, 12)
                bad[key] = value
                code, out, _, stderr, _ = self.run_gate({E: [bad], D: [run(D, 11)]})
                self.assertEqual(code, 0, stderr)
                self.assertEqual(out['sha'], D)

    def test_out_of_order_completion_still_deploys_the_newest_green_commit(self):
        # D finished first; then C's late completion triggers a run. D, not C, is selected.
        code, out, _, stderr, _ = self.run_gate({E: [run(E, 12, 'in_progress', None)], D: [run(D, 11)], C: [run(C, 10)]}, trigger=C)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(out['sha'], D)

    def test_only_first_parents_are_searched(self):
        # T (merged by D) has a green run but is not a main head; it is never consulted.
        code, out, _, stderr, calls = self.run_gate({T: [run(T, 99)], B: [run(B, 9)]})
        self.assertEqual(code, 0, stderr)
        self.assertEqual(out['sha'], B)
        self.assertFalse(any('head_sha=' + T in request.full_url for request, _ in calls))

    def test_nothing_green_holds_with_a_warning_and_no_sha(self):
        code, out, stdout, stderr, _ = self.run_gate({E: [run(E, 12, 'in_progress', None)]})
        self.assertEqual(code, 0, stderr)
        self.assertEqual((out['eligible'], out['sha']), ('false', ''))
        self.assertIn('no commit among the newest 5', out['reason'])
        self.assertIn('::warning title=Deploy held::', stdout)

    def test_search_depth_is_bounded(self):
        chain = ['%040x' % n for n in range(1, 40)][::-1]
        history = [commit(sha, parent) for sha, parent in zip(chain, chain[1:])] + [commit(chain[-1])]
        code, out, _, stderr, calls = self.run_gate({chain[-1]: [run(chain[-1], 1)]}, head=chain[0], history=history)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(out['eligible'], 'false')
        self.assertEqual(sum('/actions/workflows/ci.yml/runs' in request.full_url for request, _ in calls), 20)

    def test_non_main_or_bad_identity_fails_before_reads(self):
        for ref, trigger, event in [('refs/heads/topic', E, 'workflow_dispatch'), ('refs/tags/main', E, 'workflow_run'),
                                    ('refs/heads/main', '', 'workflow_run'), ('refs/heads/main', 'invalid', 'workflow_run'),
                                    ('refs/heads/main', E, 'pull_request')]:
            with self.subTest(ref=ref, trigger=trigger, event=event):
                code, out, _, stderr, calls = self.run_gate({E: [run(E, 9)]}, ref=ref, trigger=trigger, event=event)
                self.assertEqual(code, 1)
                self.assertEqual(out, {})
                self.assertIn('::error::', stderr)
                self.assertEqual(calls, [])

    def test_bad_main_history_or_ci_metadata_fails_closed(self):
        for doc in ([], {}, {'ref': 'refs/heads/main'}, {'ref': 'refs/heads/topic', 'object': {'type': 'commit', 'sha': E}},
                    {'ref': 'refs/heads/main', 'object': {'type': 'tag', 'sha': E}},
                    {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': None}},
                    {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'bad'}}):
            with self.subTest(main=doc):
                code, out, _, _, _ = self.run_gate({E: [run(E, 9)]}, main=doc)
                self.assertEqual((code, out), (1, {}))
        for history in ({}, [None], [{'sha': E}], [commit(D, C)], [{'sha': 'bad', 'parents': []}]):
            with self.subTest(history=history):
                code, out, _, _, _ = self.run_gate({E: [run(E, 9)]}, history=history)
                self.assertEqual((code, out), (1, {}))
        for listing in ({}, {'total_count': 2, 'workflow_runs': [run(E, 9)]}, {'total_count': 101, 'workflow_runs': [run(E, 9)]},
                        {'total_count': True, 'workflow_runs': [run(E, 9)]}, {'total_count': 1, 'workflow_runs': [None]},
                        {'total_count': 1, 'workflow_runs': [run(E, '9')]}, {'total_count': 1, 'workflow_runs': [run(E, 0)]}):
            with self.subTest(listing=listing):
                code, out, _, _, _ = self.run_gate({E: listing})
                self.assertEqual((code, out), (1, {}))

    def test_network_failures_fail_closed(self):
        for error in (URLError('unavailable'), TimeoutError('timeout')):
            with self.subTest(error=error):
                code, out, _, stderr, _ = self.run_gate({}, error=error)
                self.assertEqual((code, out), (1, {}))
                self.assertIn('eligibility unavailable', stderr)

    def test_main_moving_past_the_selection_still_passes_the_ancestry_recheck(self):
        code, out, _, stderr, _ = self.run_gate({E: [run(E, 9)]})
        self.assertEqual(out['sha'], E, stderr)
        newer = '1' * 40
        def metadata(path):
            if '/git/ref/' in path:
                return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': newer}}
            if '/compare/' in path:
                self.assertIn('/compare/' + E + '...' + newer, path)
                return {'status': 'ahead', 'ahead_by': 1, 'behind_by': 0}
            return {'total_count': 1, 'workflow_runs': [run(E, 9)]}
        self.assertEqual(guard.verify_source(REPO, 'refs/heads/main', E, metadata), 9)

    def test_serialized_workflow_wiring_and_rollback_boundary(self):
        self.assertIn('group: deploy-cloudflare\n  cancel-in-progress: false', SOURCE)
        gate = SOURCE.split('\n  source:', 1)[1]
        self.assertNotIn('secrets.', gate)
        self.assertNotIn('actions/checkout', gate)
        self.assertIn('TRIGGER_SHA: ${{ github.event.workflow_run.head_sha || github.sha }}', gate)
        for condition in ("github.event.workflow_run.conclusion == 'success'", "github.event.workflow_run.event == 'push'",
                          "github.event.workflow_run.head_branch == 'main'"):
            self.assertIn(condition, gate)
            self.assertIn(condition, DEPLOY_JOB)
        deploy = DEPLOY_JOB
        self.assertIn('needs: source', deploy)
        self.assertIn("needs.source.result == 'success' && needs.source.outputs.eligible == 'true'", deploy)
        # The selected commit is what is checked out, rechecked and named in the Worker version.
        self.assertIn('ref: ${{ needs.source.outputs.sha }}', deploy)
        self.assertIn('DEPLOY_SHA: ${{ needs.source.outputs.sha }}', deploy)
        # GITHUB_SHA (the newer main head) appears only to relabel a pre-change deploy script.
        uses = [line.strip() for line in deploy.splitlines() if 'GITHUB_SHA' in line and not line.strip().startswith('#')]
        self.assertEqual(uses, ['GITHUB_SHA="$DEPLOY_SHA" bash scripts/cloudflare_deploy.sh'])
        script = (ROOT / 'scripts/cloudflare_deploy.sh').read_text()
        self.assertIn('--message "${DEPLOY_SHA:-${GITHUB_SHA:-local}} run ${GITHUB_RUN_ID:-local}"', script)
        guard_run = 'run: python3 "$CONTROLLER/scripts/check_deploy_source.py"'
        check = deploy.index(guard_run)
        check_step = deploy[deploy.rfind('      - name:', 0, check):check]
        self.assertNotIn('if:', check_step, 'all eligible deployments recheck exact CI')
        self.assertLess(check, deploy.index('- uses: actions/setup-node'))
        production = deploy.index('Read the commit production serves')
        final = deploy.index('Recheck source immediately before production writes')
        write = deploy.index('id: deploy')
        self.assertGreater(production, deploy.index('Require a smoke-test address before deploying'))
        self.assertLess(production, final)
        self.assertLess(final, write)
        self.assertEqual(deploy.count(guard_run), 2)
        self.assertIn(guard_run + ' --production', deploy[final:write])
        for line in ('PRODUCTION_STATE: ${{ steps.production.outputs.state }}', 'PRODUCTION_SHA: ${{ steps.production.outputs.sha }}',
                     'PRODUCTION_REASON: ${{ steps.production.outputs.reason }}'):
            self.assertIn(line, deploy[final:write])
        self.assertIn("if: steps.recheck.outputs.hold == 'false'", deploy[write:write + 200])
        # Reading production only lists; every Wrangler write happens in the deploy step or a rollback.
        read_step = deploy[production:final]
        commands = sorted(line.split('$WRANGLER ', 1)[1].split()[0:2] for line in read_step.splitlines() if '$WRANGLER ' in line)
        self.assertEqual(commands, [['deployments', 'list'], ['versions', 'list']])
        self.assertIn('node "$CONTROLLER/scripts/worker_versions.mjs" live-commit', read_step)
        self.assertNotIn('exit 1', read_step, 'an unreadable production is a hold, decided by the recheck')
        self.assertIn("if: steps.deploy.outputs.deployed == 'true'", deploy, 'the smoke test is unchanged')
        self.assertIn("if: failure() && steps.deploy.outputs.deployed == 'true'", deploy, 'the rollback is unchanged')
        self.assertNotIn('needs: source', ROLLBACK)
        self.assertNotIn('check_deploy_source', ROLLBACK)
        self.assertIn("inputs.action == 'rollback'", ROLLBACK)


class ReportTests(unittest.TestCase):
    BASE = {'GITHUB_REPOSITORY': REPO, 'REPORT_TOKEN': 'checks-only', 'TRIGGER_SHA': C, 'SOURCE_ELIGIBLE': 'true',
            'SOURCE_REASON': 'newest main commit with successful Offline checks', 'SELECTED_SHA': D,
            'DEPLOY_RESULT': 'success', 'DEPLOY_HELD': 'false', 'DEPLOY_REASON': '', 'DEPLOYED': 'true', 'PRODUCTION_SHA': B}

    def report(self, error=None, **overrides):
        posts = []
        def respond(request, timeout):
            posts.append((request, json.loads(request.data), timeout))
            if error:
                raise error
            return io.BytesIO(b'{"id": 7}')
        with tempfile.TemporaryDirectory() as temp:
            summary = Path(temp) / 'summary'
            env = {**self.BASE, **overrides, 'GITHUB_STEP_SUMMARY': str(summary)}
            stdout = io.StringIO()
            code = 0
            with patch.dict(os.environ, env), patch('urllib.request.OpenerDirector.open', side_effect=respond), \
                    contextlib.redirect_stdout(stdout):
                try:
                    exec(compile(REPORT_SCRIPT, 'workflow-report', 'exec'), {'__name__': '__main__'})
                except SystemExit as stop:
                    code = stop.code or 0
            return code, posts, summary.read_text() if summary.exists() else '', stdout.getvalue()

    def test_deployed_reports_success_on_the_deployed_commit(self):
        code, posts, summary, _ = self.report()
        self.assertEqual(code, 0)
        request, body, timeout = posts[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/' + REPO + '/check-runs')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer checks-only')
        self.assertEqual((body['name'], body['head_sha'], body['status'], body['conclusion']),
                         ('Cloudflare deploy', D, 'completed', 'success'))
        self.assertIn('Deploy to Cloudflare: deployed', summary)
        self.assertEqual(timeout, 15)

    def test_held_runs_report_neutral_never_success(self):
        cases = [({'SOURCE_ELIGIBLE': 'false', 'SELECTED_SHA': '', 'SOURCE_REASON': 'no commit among the newest 20',
                   'DEPLOY_RESULT': 'skipped', 'DEPLOYED': '', 'DEPLOY_HELD': ''}, C, 'no commit among the newest 20'),
                 ({'DEPLOY_HELD': 'true', 'DEPLOY_REASON': 'production already serves ' + D, 'DEPLOYED': ''}, D,
                  'production already serves ' + D),
                 ({'DEPLOY_RESULT': 'skipped', 'DEPLOYED': '', 'DEPLOY_HELD': ''}, D, 'did not run'),
                 ({'DEPLOYED': '', 'PRODUCTION_SHA': '', 'PRODUCTION_STATE': 'unconfigured'}, D, 'not configured'),
                 ({'DEPLOYED': '', 'PRODUCTION_SHA': '', 'PRODUCTION_STATE': 'known'}, D, 'reported no deployment'),
                 ({'DEPLOY_HELD': 'true', 'DEPLOYED': '', 'PRODUCTION_SHA': '', 'PRODUCTION_STATE': 'unknown',
                   'DEPLOY_REASON': 'the commit production serves could not be traced (split traffic)'}, D, 'could not be traced')]
        for overrides, sha, why in cases:
            with self.subTest(why=why):
                code, posts, summary, stdout = self.report(**overrides)
                self.assertEqual(code, 0)
                body = posts[0][1]
                self.assertEqual((body['conclusion'], body['head_sha']), ('neutral', sha))
                self.assertIn(why, body['output']['summary'] + body['output']['title'])
                self.assertIn('HELD (nothing deployed)', summary)
                self.assertIn(why, stdout)

    def test_a_failed_check_run_write_warns_without_failing(self):
        code, posts, summary, stdout = self.report(error=URLError('denied'), DEPLOY_HELD='true', DEPLOYED='', DEPLOY_REASON='held')
        self.assertEqual((code, len(posts)), (0, 1))
        self.assertIn('::warning::Could not create the deploy check run', stdout)
        self.assertIn('HELD', summary)

    def test_report_job_is_check_write_only_and_runs_after_holds_not_failures(self):
        self.assertIn('needs: [source, deploy]', REPORT)
        self.assertIn("needs.source.result == 'success' && !cancelled()", REPORT)
        self.assertIn("(needs.deploy.result == 'success' || needs.deploy.result == 'skipped')", REPORT)
        self.assertIn('    permissions:\n      checks: write\n    env:', REPORT)
        self.assertNotIn('secrets.', REPORT)
        self.assertNotIn('actions/checkout', REPORT)
        self.assertIn('REPORT_TOKEN: ${{ github.token }}', REPORT)
        self.assertIn('PRODUCTION_STATE: ${{ needs.deploy.outputs.production_state }}', REPORT)
        self.assertIn('production_state: ${{ steps.production.outputs.state }}', DEPLOY_JOB)

    def test_one_held_report_path(self):
        # #765's current-main-only `held` job and source output are folded into the report job.
        self.assertNotIn('\n  held:\n', WORKFLOW)
        self.assertNotIn('outputs.held', SOURCE)
        self.assertEqual(WORKFLOW.count("python3 - <<'PY'"), 2, 'the source selection and the report')


if __name__ == '__main__':
    unittest.main()

"""Run the deploy job's real guard and deploy steps: this revision's controller with a pre-change candidate.

The source job may select an older checked ancestor of main, one that predates this
workflow's guard. The deploy job must then run the guard and the live-commit helper
from the controller (the workflow's own revision), refuse any checkout that is not
the selected commit, hold whenever production's commit cannot be traced, and still
label the Worker version with the selected commit. This harness checks out such a
candidate (tests/fixtures/deploy-candidate-65a0232a6), stubs `npx` (Wrangler) and the
GitHub metadata API, and executes the workflow's own step scripts in order.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests._support import ROOT

WORKFLOW = (ROOT / '.github/workflows/deploy-cloudflare.yml').read_text()
DEPLOY_JOB = WORKFLOW.split('\n  deploy:', 1)[1].split('\n  report:', 1)[0]
FIXTURE = ROOT / 'tests/fixtures/deploy-candidate-65a0232a6'
BASE = '65a0232a6'
REPO = 'Grahammmm/skippercast'
PROD, HEAD = '1' * 40, '9' * 40  # an older production commit and a newer main head whose CI is pending
RUN_ID = '4242'
LISTS = ('deployments list', 'versions list')

FAKE_NPX = r'''#!/bin/sh
# Stand-in for `npx --yes wrangler@...`: logs every call, answers the listings and D1 reads.
echo "$*" >> "$FAKE_LOG"
case "$*" in
  *"deployments list"*) [ -n "$FAKE_LIST_FAIL" ] && { echo "Authentication error [code: 10000]" >&2; exit 1; }; cat "$FAKE_DEPLOYMENTS";;
  *"versions list"*) [ -n "$FAKE_LIST_FAIL" ] && exit 1; cat "$FAKE_VERSIONS";;
  *"d1 list"*) echo '[{"name":"skippercast","uuid":"00000000-0000-4000-8000-000000000001"}]';;
  *"time-travel info"*) echo '{"bookmark":"bm-1"}';;
esac
exit 0
'''

# Stand-in for python3: check_deploy_source.py runs against fake GitHub metadata (and is
# logged, so a test can tell which copy ran); anything else runs on the real interpreter.
BOOT = r'''
import io, json, os, runpy, sys
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
import urllib.request
args = sys.argv[1:]
if not (args and args[0].endswith('check_deploy_source.py')):
    os.execv(os.environ['HARNESS_PYTHON'], [os.environ['HARNESS_PYTHON']] + args)
with open(os.environ['HARNESS_GUARD_LOG'], 'a') as log:
    log.write(os.path.realpath(args[0]) + '\n')
meta = json.load(open(os.environ['HARNESS_META']))
chain = meta['chain']
def respond(self, request, timeout=None):
    url = urlsplit(request.full_url)
    if url.path.endswith('/git/ref/heads/main'):
        doc = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': chain[-1]}}
    elif '/compare/' in url.path:
        base, head = url.path.rsplit('/compare/', 1)[1].split('...')
        if base not in chain or head not in chain:
            raise HTTPError(request.full_url, 404, 'Not Found', {}, None)
        i, j = chain.index(base), chain.index(head)
        doc = {'status': 'identical' if i == j else 'ahead' if i < j else 'behind',
               'ahead_by': max(j - i, 0), 'behind_by': max(i - j, 0)}
    elif url.path.endswith('/actions/workflows/ci.yml/runs'):
        sha = parse_qs(url.query)['head_sha'][0]
        state = meta['ci'].get(sha)
        runs = [] if state is None else [{
            'id': 100 + chain.index(sha), 'name': 'Offline checks', 'path': '.github/workflows/ci.yml',
            'event': 'push', 'head_branch': 'main', 'head_sha': sha, 'head_repository': {'full_name': meta['repo']},
            'status': 'completed' if state in ('success', 'failure') else state,
            'conclusion': state if state in ('success', 'failure') else None}]
        doc = {'total_count': len(runs), 'workflow_runs': runs}
    else:
        raise AssertionError('unexpected metadata read ' + request.full_url)
    return io.BytesIO(json.dumps(doc).encode())
urllib.request.OpenerDirector.open = respond
sys.argv = args
runpy.run_path(args[0], run_name='__main__')
'''


def step(name):
    """The run script of the deploy job's step called name, dedented as the runner sees it."""
    start = DEPLOY_JOB.index('      - name: ' + name + '\n')
    end = DEPLOY_JOB.find('\n      - ', start + 1)
    body = DEPLOY_JOB[start:end if end > 0 else len(DEPLOY_JOB)]
    if '        run: |\n' not in body:
        return body.split('        run: ', 1)[1].strip()
    lines = []
    for line in body.split('        run: |\n', 1)[1].splitlines():
        if line.strip() and not line.startswith(' ' * 10):
            break
        lines.append(line)
    return textwrap.dedent('\n'.join(lines))


def code(version_id, at, sha):
    return {'id': version_id, 'metadata': {'created_on': at, 'source': 'wrangler'},
            'annotations': {'workers/triggered_by': 'upload', 'workers/message': sha + ' run 1'}}


def secrets(version_id, at):
    return {'id': version_id, 'metadata': {'created_on': at, 'source': 'wrangler'},
            'annotations': {'workers/triggered_by': 'secret'}}


def deployment(deployment_id, at, *served):
    return {'id': deployment_id, 'created_on': at, 'source': 'wrangler', 'strategy': 'percentage',
            'versions': [{'version_id': v, 'percentage': p} for v, p in served]}


# Production serves PROD: its code upload and then its secrets upload.
VERSIONS = [code('v-prod', '2026-10-20T12:00:00Z', PROD), secrets('v-prod-s', '2026-10-20T12:00:05Z')]
DEPLOYMENTS = [deployment('d1', '2026-10-20T12:00:00Z', ('v-prod', 100)),
               deployment('d2', '2026-10-20T12:00:05Z', ('v-prod-s', 100))]


class ControllerWithPreChangeCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = Path(tempfile.mkdtemp(prefix='deploy-controller-'))
        cls.addClassCleanup(shutil.rmtree, cls.temp, True)
        cls.candidate = cls.temp / 'workspace'
        scripts = cls.candidate / 'scripts'
        scripts.mkdir(parents=True)
        for name in ('cloudflare_deploy.sh', 'check_deploy_source.py', 'worker_versions.mjs'):
            shutil.copy(FIXTURE / (name + '.txt'), scripts / name)
        for name in ('wrangler_config.mjs', 'r2_lifecycle.py'):
            shutil.copy(ROOT / 'scripts' / name, scripts / name)
        shutil.copy(ROOT / 'wrangler.jsonc', cls.candidate / 'wrangler.jsonc')
        git = ['git', '-C', str(cls.candidate), '-c', 'user.name=t', '-c', 'user.email=t@example.com']
        subprocess.run(['git', 'init', '-q', str(cls.candidate)], check=True)
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-q', '-m', 'pre-change candidate'], check=True)
        cls.sha = subprocess.run(git + ['rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
        cls.bin = cls.temp / 'bin'
        cls.bin.mkdir()
        (cls.bin / 'npx').write_text(FAKE_NPX)
        (cls.temp / 'boot.py').write_text(BOOT)
        (cls.bin / 'python3').write_text('#!/bin/sh\nexec "$HARNESS_PYTHON" "$HARNESS_BOOT" "$@"\n')
        for tool in ('npx', 'python3'):
            (cls.bin / tool).chmod(0o755)

    def setUp(self):
        self.run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=self.temp))
        self.addCleanup(shutil.rmtree, self.run_dir, True)
        subprocess.run(['git', '-C', str(self.candidate), 'clean', '-qfdx'], check=True)
        self.log = self.run_dir / 'wrangler.log'
        self.guards = self.run_dir / 'guards.log'
        self.output = self.run_dir / 'output'

    def env(self, deployments=DEPLOYMENTS, versions=VERSIONS, ci=None, event='workflow_run', deploy_sha=None,
            configured=True, list_fail=False):
        meta = self.run_dir / 'meta.json'
        meta.write_text(json.dumps({'repo': REPO, 'chain': [PROD, self.sha, HEAD],
                                    'ci': ci or {PROD: 'success', self.sha: 'success', HEAD: 'in_progress'}}))
        (self.run_dir / 'deployments.json').write_text(json.dumps(deployments))
        (self.run_dir / 'versions.json').write_text(json.dumps(versions))
        env = {key: value for key, value in os.environ.items() if not key.startswith(('GITHUB_', 'CLOUDFLARE_', 'FAKE_'))}
        env.update({
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'], 'HARNESS_PYTHON': sys.executable,
            'HARNESS_BOOT': str(self.temp / 'boot.py'), 'HARNESS_META': str(meta), 'HARNESS_GUARD_LOG': str(self.guards),
            'FAKE_LOG': str(self.log), 'FAKE_DEPLOYMENTS': str(self.run_dir / 'deployments.json'),
            'FAKE_VERSIONS': str(self.run_dir / 'versions.json'), 'WRANGLER': 'npx --yes wrangler@4.142.0',
            # The runner's own values: GITHUB_SHA is the newer main head the workflow file came from.
            'GITHUB_EVENT_NAME': event, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_REPOSITORY': REPO, 'GITHUB_SHA': HEAD,
            'GITHUB_RUN_ID': RUN_ID, 'GITHUB_OUTPUT': str(self.output), 'GITHUB_ENV': str(self.run_dir / 'env'),
            'RUNNER_TEMP': str(self.run_dir / 'runner-temp'), 'DEPLOY_SHA': deploy_sha or self.sha,
            'DEPLOY_TREE': str(self.candidate), 'SOURCE_READ_TOKEN': 'read-only',
            'VAPID_PUBLIC_KEY': 'p' * 87, 'VAPID_PRIVATE_KEY': 'k' * 43,
        })
        if configured:
            env.update({'CLOUDFLARE_API_TOKEN': 'token', 'CLOUDFLARE_ACCOUNT_ID': 'account'})
        if list_fail:
            env['FAKE_LIST_FAIL'] = '1'
        (self.run_dir / 'runner-temp').mkdir(exist_ok=True)
        return env

    def bash(self, script, env):
        # GitHub's `shell: bash`: bash --noprofile --norc -eo pipefail.
        return subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c', script], cwd=self.candidate,
                              env=env, capture_output=True, text=True, timeout=120)

    def outputs(self):
        text = self.output.read_text() if self.output.exists() else ''
        found = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        self.output.unlink(missing_ok=True)
        return found

    def wrangler_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def deploy_job(self, **options):
        """Run the deploy job's steps from the controller checkout to the deploy step. Returns (step results, outputs)."""
        env = self.env(**options)
        controller = self.candidate / '.deploy-controller/scripts'
        controller.mkdir(parents=True)  # what the sparse controller checkout writes
        for name in ('check_deploy_source.py', 'worker_versions.mjs'):
            shutil.copy(ROOT / 'scripts' / name, controller / name)
        results = {}
        moved = self.bash(step('Move the deploy controller out of the candidate tree'), env)
        self.assertEqual(moved.returncode, 0, moved.stderr)
        self.assertFalse((self.candidate / '.deploy-controller').exists(), 'the controller leaves the candidate tree')
        env.update(tuple(line.split('=', 1)) for line in Path(env['GITHUB_ENV']).read_text().splitlines())
        results['guard'] = self.bash(step('Require a main commit with successful exact-SHA CI'), env)
        if results['guard'].returncode:
            return results, {}
        production = self.bash(step('Read the commit production serves'), env)
        results['production'] = production
        self.assertEqual(production.returncode, 0, production.stderr)
        read = self.outputs()
        env.update({'PRODUCTION_STATE': read.get('state', ''), 'PRODUCTION_SHA': read.get('sha', ''),
                    'PRODUCTION_REASON': read.get('reason', '')})
        results['recheck'] = self.bash(step('Recheck source immediately before production writes'), env)
        recheck = self.outputs()
        # The deploy step's condition: if: steps.recheck.outputs.hold == 'false'.
        if results['recheck'].returncode == 0 and recheck.get('hold') == 'false':
            results['deploy'] = self.bash(step('Back up D1, migrate and deploy'), env)
        return results, {**{'production_' + k: v for k, v in read.items()}, **recheck, **self.outputs()}

    def assert_only_controller_guards_ran(self):
        ran = set(self.guards.read_text().splitlines())
        self.assertTrue(ran)
        self.assertEqual({Path(path).parent.parent.name for path in ran}, {'deploy-controller'}, ran)

    def assert_no_production_writes(self):
        calls = self.wrangler_calls()
        self.assertTrue(all(any(listing in call for listing in LISTS) for call in calls), calls)

    def test_fixture_is_the_pre_change_main(self):
        old = (FIXTURE / 'check_deploy_source.py.txt').read_text()
        self.assertIn("raise SourceError('selected SHA is not current main; dispatch main again')", old)
        self.assertNotIn('live-commit', (FIXTURE / 'worker_versions.mjs.txt').read_text())
        self.assertIn('--message "${GITHUB_SHA:-local} run ${GITHUB_RUN_ID:-local}"', (FIXTURE / 'cloudflare_deploy.sh.txt').read_text())
        for name in ('cloudflare_deploy.sh', 'check_deploy_source.py', 'worker_versions.mjs'):
            shown = subprocess.run(['git', '-C', str(ROOT), 'show', BASE + ':scripts/' + name], capture_output=True, text=True)
            if shown.returncode == 0:  # a shallow CI clone lacks the commit; the content checks above still hold
                self.assertEqual(shown.stdout, (FIXTURE / (name + '.txt')).read_text(), name)

    def test_the_candidates_own_guard_would_refuse_an_older_checked_ancestor(self):
        # Why the controller exists: the pre-change guard checks GITHUB_SHA and demands current main.
        env = self.env()
        old = self.bash('python3 scripts/check_deploy_source.py', env)
        self.assertEqual(old.returncode, 1)
        self.assertIn('has not succeeded', old.stderr, 'the runner GITHUB_SHA is the pending head')
        old = self.bash('python3 scripts/check_deploy_source.py', {**env, 'GITHUB_SHA': self.sha})
        self.assertEqual(old.returncode, 1)
        self.assertIn('selected SHA is not current main', old.stderr)

    def test_an_older_checked_candidate_deploys_from_the_controller_labelled_with_its_own_sha(self):
        results, out = self.deploy_job()
        self.assertEqual(results['guard'].returncode, 0, results['guard'].stderr)
        self.assertEqual((out['production_state'], out['production_sha']), ('known', PROD))
        self.assertEqual(out['hold'], 'false', results['recheck'].stdout + results['recheck'].stderr)
        self.assertEqual(results['deploy'].returncode, 0, results['deploy'].stdout + results['deploy'].stderr)
        self.assertEqual(out.get('deployed'), 'true')
        self.assertEqual(out.get('previous_version'), 'v-prod-s')
        calls = self.wrangler_calls()
        self.assertIn('--yes wrangler@4.142.0 deploy --config wrangler.deploy.jsonc --message ' + self.sha + ' run ' + RUN_ID, calls)
        self.assertTrue(any('r2 object put skippercast-backups/d1/' in c and c.split()[5].endswith('-' + self.sha + '.sql')
                            for c in calls), calls)
        self.assertFalse(any(HEAD in call for call in calls), 'the newer, unchecked main head never labels anything')
        self.assert_only_controller_guards_ran()

    def test_without_the_label_override_the_old_script_would_name_the_unchecked_head(self):
        # Control for the GITHUB_SHA prefix in the deploy step: the runner's GITHUB_SHA is the newer head.
        env = self.env()
        run = self.bash('mkdir -p var && bash scripts/cloudflare_deploy.sh', env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(any(call.endswith('--message ' + HEAD + ' run ' + RUN_ID) for call in self.wrangler_calls()))
        self.assertIn('GITHUB_SHA="$DEPLOY_SHA" bash scripts/cloudflare_deploy.sh', step('Back up D1, migrate and deploy'))

    def test_unknown_production_holds_on_every_event_without_writes(self):
        untagged = VERSIONS + [{'id': 'v-hand', 'metadata': {'created_on': '2026-10-20T13:00:00Z'},
                                'annotations': {'workers/triggered_by': 'upload'}}]
        cases = {
            'untagged code upload live': dict(versions=untagged,
                                              deployments=DEPLOYMENTS + [deployment('d3', '2026-10-20T13:00:00Z', ('v-hand', 100))]),
            'split traffic': dict(deployments=DEPLOYMENTS + [deployment('d3', '2026-10-20T13:00:00Z', ('v-prod-s', 90), ('v-prod', 10))]),
            'live version missing': dict(versions=VERSIONS[:1]),
            'no deployments': dict(deployments=[]),
            'listing fails': dict(list_fail=True),
            'secrets change without its code version': dict(versions=VERSIONS[1:]),
        }
        for event in ('workflow_run', 'workflow_dispatch'):
            for why, options in cases.items():
                with self.subTest(event=event, case=why):
                    self.log.unlink(missing_ok=True)
                    results, out = self.deploy_job(event=event, **options)
                    self.assertEqual(out['production_state'], 'unknown')
                    self.assertEqual(out['production_sha'], '')
                    self.assertIn('::warning title=Production commit unknown::', results['production'].stdout)
                    self.assertEqual(results['recheck'].returncode, 0, results['recheck'].stderr)
                    self.assertEqual(out['hold'], 'true')
                    self.assertIn('could not be traced', out['reason'])
                    self.assertNotIn('deploy', results)
                    self.assert_no_production_writes()
                    self.assert_only_controller_guards_ran()
                    self.guards.unlink()
                    subprocess.run(['git', '-C', str(self.candidate), 'clean', '-qfdx'], check=True)

    def test_production_at_or_past_the_candidate_holds_without_writes(self):
        live = lambda sha: dict(versions=VERSIONS + [code('v-new', '2026-10-20T13:00:00Z', sha)],
                                deployments=DEPLOYMENTS + [deployment('d3', '2026-10-20T13:00:00Z', ('v-new', 100))])
        for sha, why in ((HEAD, 'which is newer than'), (self.sha, 'production already serves ' + self.sha)):
            with self.subTest(production=sha):
                self.log.unlink(missing_ok=True)
                results, out = self.deploy_job(**live(sha))
                self.assertEqual((out['production_state'], out['production_sha'], out['hold']), ('known', sha, 'true'))
                self.assertIn(why, out['reason'])
                self.assertNotIn('deploy', results)
                self.assert_no_production_writes()
                subprocess.run(['git', '-C', str(self.candidate), 'clean', '-qfdx'], check=True)

    def test_unconfigured_cloudflare_reads_and_writes_nothing(self):
        results, out = self.deploy_job(configured=False)
        self.assertEqual(out['production_state'], 'unconfigured')
        self.assertEqual(out['hold'], 'false')
        self.assertEqual(results['deploy'].returncode, 0, results['deploy'].stderr)
        self.assertIn('Cloudflare is not configured', results['deploy'].stdout)
        self.assertNotIn('deployed', out)
        self.assertEqual(self.wrangler_calls(), [])

    def test_a_checkout_that_is_not_the_selected_commit_is_refused_before_anything_else(self):
        # DEPLOY_SHA names a green ancestor (PROD), but the workspace holds a different commit.
        results, _ = self.deploy_job(deploy_sha=PROD)
        self.assertEqual(results['guard'].returncode, 1)
        self.assertIn('the candidate checkout is ' + self.sha + ', not ' + PROD, results['guard'].stderr)
        self.assertNotIn('production', results)
        self.assertEqual(self.wrangler_calls(), [])

    def test_a_failed_or_pending_candidate_never_reaches_production(self):
        for state in ('failure', 'in_progress'):
            with self.subTest(state=state):
                results, _ = self.deploy_job(ci={PROD: 'success', self.sha: state, HEAD: 'in_progress'})
                self.assertEqual(results['guard'].returncode, 1)
                self.assertIn('has not succeeded', results['guard'].stderr)
                self.assertEqual(self.wrangler_calls(), [])
                subprocess.run(['git', '-C', str(self.candidate), 'clean', '-qfdx'], check=True)

    def test_workflow_runs_guards_only_from_the_controller(self):
        self.assertIn('ref: ${{ github.workflow_sha }}\n          path: .deploy-controller\n          persist-credentials: false',
                      DEPLOY_JOB)
        controller = DEPLOY_JOB.index('path: .deploy-controller')
        self.assertLess(DEPLOY_JOB.index('ref: ${{ needs.source.outputs.sha }}'), controller,
                        'the candidate checkout first: a later root checkout would wipe the controller')
        self.assertNotIn('python3 scripts/check_deploy_source.py', DEPLOY_JOB)
        self.assertNotIn('node scripts/worker_versions.mjs live-commit', DEPLOY_JOB)
        self.assertEqual(DEPLOY_JOB.count('python3 "$CONTROLLER/scripts/check_deploy_source.py"'), 2)
        self.assertEqual(DEPLOY_JOB.count('DEPLOY_TREE: ${{ github.workspace }}'), 2)
        self.assertLess(controller, DEPLOY_JOB.index('Install locked web dependencies'))


if __name__ == '__main__':
    unittest.main()

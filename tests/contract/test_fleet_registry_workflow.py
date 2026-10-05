"""The charter fleet registry workflow keeps the shape design.md section 9 and runners.md require (CF-18).

Weekly (Mon 09:47 UTC) and on dispatch (region, sink, steps; run_id to resume), no
pull_request trigger, dark until ENABLE_FLEET, only on our own runner and only from
main, the OIDC identity the Worker pins, the Places key only in the pipeline step, run
state outside the checkout, and a runbook for the first run, reruns and staging runs.
"""
import json
import re
import unittest

from tests._support import ROOT

WORKFLOW = ROOT / '.github' / 'workflows' / 'fleet-registry.yml'
RUNBOOK = ROOT / 'docs' / 'operations' / 'runbooks' / 'fleet-registry.md'


def _steps(text):
    """Each `- name:` / `- uses:` step of the job, as text."""
    body = text.split('\n    steps:\n', 1)[1]
    return re.split(r'\n(?=      - )', body)


class FleetRegistryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        # Comments removed, so prose such as "No pull_request trigger" is not read as a trigger.
        self.header = '\n'.join(line for line in self.text.split('\njobs:', 1)[0].splitlines()
                                if not line.lstrip().startswith('#'))

    def test_weekly_and_dispatch_only(self):
        on = re.search(r'\non:\n((?:[ \t].*\n?)*)', self.header + '\n').group(1)
        self.assertEqual(re.findall(r'^  ([a-z_]+):', on, re.M), ['schedule', 'workflow_dispatch'])
        self.assertIn('- cron: "47 9 * * 1"', on)
        for trigger in ('pull_request', 'push:', 'workflow_run'):
            self.assertNotIn(trigger, self.header)
        inputs = re.findall(r'^      ([a-z_]+):\n', on, re.M)
        self.assertEqual(inputs, ['region', 'sink', 'steps', 'run_id'])
        self.assertRegex(on, r'sink:\n(?:        .*\n)*?        options:\n          - worker\n          - staging\n')

    def test_dark_main_only_and_never_hosted(self):
        self.assertIn("if: vars.ENABLE_FLEET == 'true' && vars.DATA_RUNNER != '' && github.ref == 'refs/heads/main'",
                      self.text)
        self.assertEqual(re.findall(r'^\s*runs-on:\s*(.+?)\s*$', self.text, re.M),
                         ["${{ vars.DATA_RUNNER || 'ubuntu-latest' }}"])
        self.assertEqual(self.text.count('\n  run:\n'), 1, 'one job')

    def test_identity_and_least_privilege(self):
        self.assertIn('permissions: {}', self.header)
        granted = sorted(re.sub(r'\s*#.*', '', line).strip() for line in
                         re.search(r'\n    permissions:\n((?:      .*\n)+)', self.text).group(1).splitlines())
        self.assertEqual(granted, ['contents: read', 'id-token: write'])
        self.assertEqual(self.text.count('permissions:'), 2)
        self.assertIn('group: fleet-registry', self.header)
        self.assertIn('cancel-in-progress: false', self.header)
        self.assertIn('persist-credentials: false', self.text)
        policy = json.loads((ROOT / 'deployments' / 'production.json').read_text())
        self.assertIn('fleet-registry.yml', policy['scheduler']['workflows'])
        self.assertIn("'fleet-registry.yml'", (ROOT / 'server' / 'routes' / 'fleet.ts').read_text())

    def test_runs_the_pipeline_with_state_outside_the_checkout(self):
        self.assertIn('python -m pip install -e ".[fleet]"', self.text)
        steps = _steps(self.text)
        locate = next(s for s in steps if 'name: Locate the run state' in s)
        self.assertIn('var="${SKIPPERCAST_FLEET_VAR:-$HOME/.local/share/skippercast/fleet}"', locate)
        self.assertIn('if [ "$SINK" = staging ]; then var="$var-staging"; fi', locate)
        self.assertIn('echo "SKIPPERCAST_FLEET_VAR=$var" >> "$GITHUB_ENV"', locate)
        self.assertNotIn('GITHUB_WORKSPACE', self.text)
        pipeline = next(s for s in steps if 'name: Run the registry pipeline' in s)
        self.assertIn('args=(run --region "$REGION" --sink "$SINK" --run-id "$RUN_ID")', pipeline)
        self.assertIn('args+=(--steps "$STEPS")', pipeline)
        self.assertIn("REGION: ${{ inputs.region || vars.FLEET_REGION || 'CA' }}", self.text)
        self.assertIn("SINK: ${{ inputs.sink || 'worker' }}", self.text)
        coverage = next(s for s in steps if 'name: Report charter identity coverage' in s)
        self.assertIn('coverage-status --region "$REGION" --sink "$SINK"', coverage)
        self.assertNotIn('--apply', re.sub(r'#.*', '', self.text), 'region files change only through a PR')

    def test_inputs_reach_the_shell_only_through_the_environment(self):
        for line in self.text.split('\njobs:', 1)[1].splitlines():
            if '${{' in line:
                self.assertRegex(line.strip(), r'^(?:[A-Z_]+|runs-on|group): \$\{\{ [^}]+ \}\}$', line)

    def test_places_key_only_in_the_pipeline_step(self):
        self.assertEqual(self.text.count('secrets.'), 1)
        pipeline = next(s for s in _steps(self.text) if 'name: Run the registry pipeline' in s)
        self.assertIn('GOOGLE_PLACES_API_KEY: ${{ secrets.GOOGLE_PLACES_API_KEY }}', pipeline)


class FleetRegistryRunbookTests(unittest.TestCase):
    def setUp(self):
        self.text = RUNBOOK.read_text(encoding='utf-8')

    def test_covers_first_run_reruns_and_staging_runs(self):
        for heading in ('## First run', '## Reruns', '## Staging runs', '## Applying charter-identity coverage'):
            self.assertIn(heading, self.text)
        for needle in ('gh workflow run fleet-registry.yml', '-f sink=staging', '-f sink=worker', '-f run_id=',
                       'FLEET_ENABLED', 'ENABLE_FLEET', 'https://github.com/Grahammmm/skippercast/settings/variables/actions',
                       'GOOGLE_PLACES_API_KEY', 'discover.json', 'state.json'):
            self.assertIn(needle, self.text)
        self.assertNotRegex(self.text, r'gh workflow run fleet-registry\.yml[^\n`]*--ref', 'the workflow runs only from main')

    def test_notes_the_receipt_and_the_open_issues(self):
        self.assertIn('regions/fort-bragg-point-arena/region.json', self.text)
        self.assertIn('research/receipts/h11730-fort-bragg-regional-camera-support.json', self.text)
        self.assertIn('python -m research.lib.receipts', self.text)
        issues = set(re.findall(r'https://github\.com/Grahammmm/skippercast/issues/(\d+)', self.text))
        self.assertGreaterEqual(len(issues), 2, 'offering retirement and the source_id/priority mismatch')


if __name__ == '__main__':
    unittest.main()

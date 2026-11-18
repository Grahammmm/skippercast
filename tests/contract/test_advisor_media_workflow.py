"""The advisor-media runner job's workflow keeps the shape 09 § Derived images requires (TA-M1).

Dispatch only, dark until ENABLE_ADVISOR, on GitHub-hosted Ubuntu with ffmpeg.
The Worker pins its OIDC identity (deployments/production.json scheduler.workflows),
and the job uses only the R2 token scoped to the advisor bucket.
"""
import json
import re
import unittest

from tests._support import ROOT

WORKFLOW = ROOT / '.github' / 'workflows' / 'advisor-media.yml'


class AdvisorMediaWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        # Comments removed, so prose such as "No schedule:" is not read as a trigger.
        self.header = '\n'.join(line for line in self.text.split('\njobs:', 1)[0].splitlines() if not line.lstrip().startswith('#'))

    def test_dispatch_only(self):
        self.assertRegex(self.header, r'\non:\n  workflow_dispatch:\n')
        for trigger in ('schedule:', 'push:', 'pull_request'):
            self.assertNotIn(trigger, self.header)

    def test_dark_until_enabled_on_hosted_ubuntu(self):
        self.assertEqual(re.findall(r'^    if: (.+)$', self.text, re.M), ["vars.ENABLE_ADVISOR == 'true'"])
        self.assertEqual(re.findall(r'^\s*runs-on:\s*(.+?)\s*$', self.text, re.M), ['ubuntu-latest'])

    def test_identity_and_least_privilege(self):
        self.assertIn('permissions: {}', self.header)
        self.assertIn('id-token: write', self.text)
        self.assertIn('contents: read', self.text)
        self.assertNotRegex(self.text, r'(contents|actions|issues|pull-requests): write')
        self.assertIn('cancel-in-progress: false', self.header)
        policy = json.loads((ROOT / 'deployments' / 'production.json').read_text())
        self.assertIn('advisor-media.yml', policy['scheduler']['workflows'])
        self.assertEqual(policy['scheduler']['workflow'], '.github/workflows/live-conditions.yml', 'the trip check keeps its own')

    def test_runs_the_job_with_the_advisor_extra_and_its_scoped_token(self):
        self.assertIn('python -m pip install -e ".[advisor]"', self.text)
        commands = re.findall(r'^        run: (.+)$', self.text, re.M)
        self.assertLess(
            commands.index('sudo apt-get install -y --no-install-recommends ffmpeg'),
            commands.index('python scripts/advisor/media_job.py'),
            'install ffmpeg before deriving media',
        )
        self.assertIn('R2_ADVISOR_TOKEN: ${{ secrets.R2_ADVISOR_TOKEN }}', self.text)
        self.assertNotIn('CLOUDFLARE_API_TOKEN', self.text, 'never the broad deploy token')
        self.assertNotIn('R2_PUBLISH_TOKEN', self.text, 'the feed bucket token is not reused')
        self.assertIn("ADVISOR_PUBLIC_BASE: ${{ vars.ADVISOR_PUBLIC_BASE || 'https://skippercast.com' }}", self.text)
        self.assertIn('ADVISOR_NUMBER: ${{ vars.ADVISOR_NUMBER }}', self.text)


if __name__ == '__main__':
    unittest.main()

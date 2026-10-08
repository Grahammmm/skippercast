"""The coast asset copy (FE-85) stays a manual, least-privilege job on the owner's runner."""
import re
import unittest

from tests._support import ROOT

WORKFLOW = ROOT / '.github' / 'workflows' / 'coast-assets.yml'


class CoastAssetsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        self.header = '\n'.join(line for line in self.text.split('\njobs:', 1)[0].splitlines() if not line.lstrip().startswith('#'))

    def test_dispatch_only_from_main_on_the_owner_runner(self):
        self.assertRegex(self.header, r'\non:\n  workflow_dispatch:\n')
        for trigger in ('schedule:', 'push:', 'pull_request'):
            self.assertNotIn(trigger, self.header)
        self.assertIn("if: github.ref == 'refs/heads/main' && vars.DATA_RUNNER != ''", self.text)
        self.assertEqual(re.findall(r'^\s*runs-on:\s*(.+?)\s*$', self.text, re.M), ["${{ vars.DATA_RUNNER || 'ubuntu-latest' }}"])

    def test_least_privilege_and_the_token_only_on_the_upload_step(self):
        self.assertIn('permissions: {}', self.header)
        self.assertIn('contents: read', self.text)
        self.assertNotRegex(self.text, r': write')
        self.assertIn('persist-credentials: false', self.text)
        self.assertIn('cancel-in-progress: false', self.header)
        self.assertEqual(self.text.count('secrets.'), 3)
        upload = self.text.split('- name: Upload, read back and promote', 1)[1]
        self.assertIn('CLOUDFLARE_API_TOKEN: ${{ secrets.R2_PUBLISH_TOKEN || secrets.CLOUDFLARE_API_TOKEN }}', upload)
        self.assertNotIn('secrets.', self.text.split('- name: Upload, read back and promote', 1)[0])

    def test_rights_check_runs_before_any_download(self):
        steps = re.findall(r'run: python scripts/coast/publish_assets\.py (.+)', self.text)
        self.assertTrue(steps[0].startswith('--plan '), steps)
        self.assertNotIn('--plan', ' '.join(steps[1:]))


if __name__ == '__main__':
    unittest.main()

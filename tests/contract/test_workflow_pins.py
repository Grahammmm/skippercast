"""Every third-party GitHub Action is pinned to a full commit SHA.

A tag such as @v7 can be moved by whoever controls the action's repository, so an
unpinned `uses:` lets code we never reviewed run with our secrets. Dependabot keeps
the pinned SHAs current (with a `# vX.Y.Z` comment), so pinning costs nothing.
"""
import re
import unittest
from tests._support import ROOT


USES = re.compile(r'^\s*-?\s*uses:\s*(\S+)', re.M)


class WorkflowPinTests(unittest.TestCase):
    def test_actions_are_pinned_to_commit_shas(self):
        unpinned = []
        for path in sorted((ROOT / '.github/workflows').glob('*.y*ml')):
            for ref in USES.findall(path.read_text()):
                if ref.startswith(('./', 'docker://')):
                    continue
                if not re.fullmatch(r'[\w.-]+/[\w./-]+@[0-9a-f]{40}', ref):
                    unpinned.append(f'{path.name}: {ref}')
        self.assertEqual(unpinned, [], 'pin these actions to a full commit SHA with a # vX.Y.Z comment')

    def test_bot_pull_requests_get_required_checks(self):
        # A pull request opened with the default GITHUB_TOKEN starts no
        # pull_request workflows, so the required survey-science check never
        # runs on it (#106). Such workflows must dispatch Offline checks on the
        # branch they propose, which needs `actions: write`.
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertRegex(ci.split('permissions:', 1)[0], r'\n  workflow_dispatch:', 'ci.yml must accept workflow_dispatch')
        for path in sorted((ROOT / '.github/workflows').glob('*.y*ml')):
            text = path.read_text()
            for match in re.finditer(r'uses:\s*peter-evans/create-pull-request@\S+.*?\n\s+with:\n((?:\s{10,}.*\n)+)', text):
                block = match.group(1)
                if re.search(r'^\s+token:', block, re.M):
                    continue
                branch = re.search(r'^\s+branch:\s*(\S+)', block, re.M).group(1)
                with self.subTest(workflow=path.name, branch=branch):
                    dispatch = f'gh workflow run ci.yml --repo "$GITHUB_REPOSITORY" --ref {branch}'
                    self.assertTrue(dispatch in text, f'dispatch Offline checks after opening the PR: {dispatch}')
                    self.assertTrue(re.search(r'\n\s+actions: write\n', text), 'the dispatching job needs actions: write')


if __name__ == '__main__':
    unittest.main()


class RunnerSwitchTests(unittest.TestCase):
    """Heavy workflows read their runner from a repository variable (docs/operations/runners.md)."""

    HOSTED_ONLY = {'deploy-cloudflare.yml', 'dco.yml', 'release.yml'}

    def test_scheduled_and_ci_jobs_run_on_the_switchable_runner(self):
        wrong = []
        for path in sorted((ROOT / '.github/workflows').glob('*.y*ml')):
            expected = "${{ vars.CI_SELF_HOSTED_READY == 'true' && vars.CI_RUNNER || 'ubuntu-latest' }}" if path.name == 'ci.yml' else "${{ vars.DATA_RUNNER || 'ubuntu-latest' }}"
            for line in re.findall(r'^\s*runs-on:\s*(.+?)\s*$', path.read_text(), re.M):
                if path.name in self.HOSTED_ONLY:
                    if line != 'ubuntu-latest':
                        wrong.append(f'{path.name}: {line} (deploy, DCO and release stay GitHub-hosted)')
                elif line == 'macos-latest' and path.name == 'research-substrate.yml':
                    continue  # one monthly audit job needs a macOS wheel (pylerc); about 90 billed minutes a month
                elif line != expected:
                    wrong.append(f'{path.name}: {line}')
        self.assertEqual(wrong, [])

    def test_runner_setup_script_pins_the_runner_release(self):
        script = (ROOT / 'scripts/runner/setup.sh').read_text()
        self.assertRegex(script, r'RUNNER_VERSION=\$\{RUNNER_VERSION:-\d+\.\d+\.\d+\}')
        self.assertRegex(script, r'RUNNER_SHA256=\$\{RUNNER_SHA256:-[0-9a-f]{64}\}')
        self.assertIn('--labels', script)
        self.assertIn('svc.sh install', script)

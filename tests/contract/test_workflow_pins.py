"""Every third-party GitHub Action is pinned to a full commit SHA.

A tag such as @v7 can be moved by whoever controls the action's repository, so an
unpinned `uses:` lets code we never reviewed run with our secrets. Dependabot keeps
the pinned SHAs current (with a `# vX.Y.Z` comment), so pinning costs nothing.
"""
import re
import unittest

import yaml

from tests._support import ROOT


USES = re.compile(r'^\s*-?\s*uses:\s*(\S+)', re.M)


class WorkflowPinTests(unittest.TestCase):
    def test_ci_checks_each_pr_and_main_without_duplicate_branch_pushes(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        header = ci.split('permissions:', 1)[0]
        self.assertRegex(header, r'\n  push:\n    branches: \[main\]\n  pull_request:\n')
        self.assertIn('\n  workflow_dispatch:\n', header)
        # Required job names and full test layers remain available on every PR.
        for name in ('survey-science', 'e2e', 'check'):
            self.assertRegex(ci, rf'\n  {name}:\n')

    def test_main_pushes_only_coalesce_pending_and_prs_cancel_running(self):
        ci = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
        # Pin the selector and fallback together: a ref-only selector would
        # let a dispatch on main replace a pending push without deploy coverage.
        concurrency = ci['concurrency']
        self.assertEqual({**concurrency, 'group': ' '.join(concurrency['group'].split())}, {
            'group': "${{ (github.event_name == 'push' && github.ref == 'refs/heads/main') "
                     "&& format('ci-main-{0}', github.ref) "
                     "|| format('{0}-{1}-{2}', github.workflow, github.event_name, "
                     "github.event.pull_request.number || github.run_id) }}",
            'cancel-in-progress': "${{ github.event_name == 'pull_request' }}",
        })
        publication = (ROOT / '.github/workflows/seafloor.yml').read_text()
        self.assertIn('group: seafloor-publication', publication)
        self.assertIn('cancel-in-progress: false', publication)

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


class RunnerSwitchTests(unittest.TestCase):
    """Public workflows never target the private runner fleet."""

    def test_workflow_runner_assignments(self):
        # Match the exact job, not the whole file: only this audit needs macOS.
        macos_job = ('research-substrate.yml', 'audit')
        macos_jobs = []
        for path in sorted((ROOT / '.github/workflows').iterdir()):
            if path.suffix not in ('.yml', '.yaml'):
                continue
            for job_id, job in yaml.safe_load(path.read_text())['jobs'].items():
                if 'runs-on' not in job and 'uses' in job:
                    continue  # Reusable workflow calls have no runner of their own.
                identity = (path.name, job_id)
                runner = job.get('runs-on')
                if runner == 'macos-latest':
                    macos_jobs.append(identity)
                expected = 'macos-latest' if identity == macos_job else 'ubuntu-latest'
                with self.subTest(workflow=path.name, job=job_id):
                    self.assertEqual(runner, expected, f'expected literal {expected}')
        self.assertEqual(macos_jobs, [macos_job])

    def test_no_private_runner_references_in_github(self):
        # Catch runner selectors copied into composite actions or workflow env,
        # even when the jobs themselves are still on GitHub-hosted runners.
        forbidden = re.compile(
            rb'''self-hosted|\bvars\s*(?:\.\s*|\[\s*['"])[a-z0-9_]*runner[a-z0-9_]*'''
            rb'|ci_self_hosted_ready', re.I,
        )
        matches = []
        for path in sorted((ROOT / '.github').rglob('*')):
            if not path.is_file():
                continue
            text = path.read_bytes()
            for match in forbidden.finditer(text):
                number = text.count(b'\n', 0, match.start()) + 1
                matches.append(f'{path.relative_to(ROOT)}:{number}: {match[0].decode()!r}')
        self.assertEqual(matches, [])

    def test_ci_uses_job_local_pnpm_and_installs_browser_dependencies(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        setups = re.findall(r'uses: pnpm/action-setup@[^\n]*\n((?:\s+[^\n]*\n)+?)(?=\s+- )', ci)
        self.assertEqual(len(setups), 2)
        for block in setups:
            self.assertIn('dest: ${{ runner.temp }}/setup-pnpm', block, 'pnpm/action-setup needs a per-job install dir')
        installs = re.findall(r'(?:if: ([^\n]+)\n\s+)?run: pnpm exec playwright install ([^\n]+)', ci)
        self.assertEqual(installs, [('', '--with-deps chromium')], 'CI must install Chromium and its system dependencies unconditionally')


if __name__ == '__main__':
    unittest.main()

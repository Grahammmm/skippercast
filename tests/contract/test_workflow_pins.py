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


if __name__ == '__main__':
    unittest.main()

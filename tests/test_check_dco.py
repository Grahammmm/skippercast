"""The DCO gate enforces sign-off for outside contributors only."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('check_dco', ROOT / 'scripts/check_dco.py')
check_dco = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_dco)


def commit(sha, name, email, message, login=None):
    return {'sha': sha * 40, 'author': {'login': login} if login else None,
            'commit': {'author': {'name': name, 'email': email}, 'message': message}}


OWNER = commit('a', 'Grahammmm', 'owner@example.com', 'Add feature', login='Grahammmm')
CODEX = commit('b', 'Grahammmm', 'owner@example.com', 'Audit source\n\nCo-authored-by: Codex', login='Grahammmm')
CLAUDE = commit('c', 'Claude', 'noreply@anthropic.com', 'Fix bug\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')
SIGNED = commit('d', 'Pat Doe', 'pat@example.org', 'Fix typo\n\nSigned-off-by: Pat Doe <pat@example.org>', login='patdoe')
UNSIGNED = commit('e', 'Pat Doe', 'pat@example.org', 'Fix typo', login='patdoe')
WRONG_EMAIL = commit('f', 'Pat Doe', 'pat@example.org', 'Fix\n\nSigned-off-by: Pat Doe <other@example.org>', login='patdoe')
UNLINKED = commit('9', 'Sam Roe', 'sam@example.net', 'Tweak')
DEPENDABOT = commit('6', 'dependabot[bot]', '49699333+dependabot[bot]@users.noreply.github.com',
                    'Bump actions/checkout from 4 to 7', login='dependabot[bot]')
SPOOFED_BOT = commit('5', 'dependabot[bot]', 'dependabot@example.com', 'Bump', login='mallory')
SPOOFED_NAME = commit('8', 'Claude', 'claude@example.com', 'Pretend to be an agent', login='mallory')


class DcoTests(unittest.TestCase):
    def test_owner_and_agents_are_exempt(self):
        self.assertEqual(check_dco.offenders([OWNER, CODEX, CLAUDE]), [])

    def test_dependabot_updates_on_repository_branches_are_exempt(self):
        # Dependabot opens its branches in this repository; its commits carry no sign-off.
        self.assertEqual(check_dco.offenders([DEPENDABOT]), [])
        # The exemption follows the GitHub login, not a name anyone can type.
        self.assertEqual(len(check_dco.offenders([SPOOFED_BOT])), 1)
        self.assertEqual(len(check_dco.offenders([DEPENDABOT], fork=True)), 1)

    def test_outside_contributor_with_matching_sign_off_passes(self):
        self.assertEqual(check_dco.offenders([SIGNED]), [])

    def test_missing_or_mismatched_sign_off_fails(self):
        found = check_dco.offenders([UNSIGNED, WRONG_EMAIL, UNLINKED])
        self.assertEqual([sha for sha, _ in found], ['e' * 12, 'f' * 12, '9' * 12])
        self.assertIn('pat@example.org', found[0][1])

    def test_exemption_is_not_granted_by_display_name(self):
        self.assertEqual(len(check_dco.offenders([SPOOFED_NAME])), 1)

    def test_sign_off_must_be_its_own_trailer_line(self):
        inline = commit('7', 'Pat Doe', 'pat@example.org', 'Mention Signed-off-by: Pat Doe <pat@example.org> inline', login='patdoe')
        self.assertEqual(len(check_dco.offenders([inline])), 1)

    def test_fork_pull_requests_get_no_exemptions(self):
        # Authorship is just an email; a fork could claim the owner's or an agent's.
        self.assertEqual(len(check_dco.offenders([OWNER, CLAUDE], fork=True)), 2)
        self.assertEqual(check_dco.offenders([SIGNED], fork=True), [])

    def test_cli_accepts_paginated_pages_and_sets_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            good, bad = Path(tmp, 'good.json'), Path(tmp, 'bad.json')
            good.write_text(json.dumps([[OWNER, CLAUDE], [SIGNED]]))
            bad.write_text(json.dumps([OWNER, UNSIGNED]))
            run = lambda p: subprocess.run([sys.executable, str(ROOT / 'scripts/check_dco.py'), str(p)],
                                           capture_output=True, text=True)
            ok, failed = run(good), run(bad)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn('3 commit(s)', ok.stdout)
        self.assertEqual(failed.returncode, 1)
        self.assertIn('eeeeeeeeeeee', failed.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            owner_only = Path(tmp, 'owner.json')
            owner_only.write_text(json.dumps([OWNER]))
            forked = subprocess.run([sys.executable, str(ROOT / 'scripts/check_dco.py'), '--fork', str(owner_only)],
                                    capture_output=True, text=True)
        self.assertEqual(forked.returncode, 1)


if __name__ == '__main__':
    unittest.main()

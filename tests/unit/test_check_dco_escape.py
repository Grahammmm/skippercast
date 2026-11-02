"""The DCO gate escapes author text in ::error:: annotations and refuses non-text author fields."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from tests._support import ROOT

SCRIPT = ROOT / 'scripts/check_dco.py'


def commit(sha, name='Pat Doe', email='pat@example.org', message='Fix typo', user=None):
    return {'sha': sha * 40, 'author': user,
            'commit': {'author': {'name': name, 'email': email}, 'message': message}}


SIGNED = commit('d', message='Fix typo\n\nSigned-off-by: Pat Doe <pat@example.org>', user={'login': 'patdoe'})


def run(*args):
    # Bytes, decoded by hand: text mode would turn a raw '\r' into '\n' and hide it.
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True)
    return subprocess.CompletedProcess(result.args, result.returncode, result.stdout.decode('utf-8'),
                                       result.stderr.decode('utf-8'))


class DcoEscapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_commits(self, commits):
        path = Path(self.tmp.name, 'commits.json')
        path.write_text(json.dumps(commits), encoding='utf-8')
        return run(path)

    def offender_lines(self, commits):
        result = self.run_commits(commits)
        self.assertEqual(result.returncode, 1, result.stderr)
        lines = result.stdout.split('\n')
        self.assertEqual(lines[-1], '', result.stdout)
        lines = lines[:-1]
        self.assertEqual(len(lines), len([c for c in commits if c is not SIGNED]), result.stdout)
        for line in lines:
            self.assertTrue(line.startswith('::error::Commit '), line)
            self.assertNotIn('\r', line)
        return lines

    def test_newline_in_name_cannot_start_a_command(self):
        lines = self.offender_lines([commit('e', name='Pat\n::warning::fake'), SIGNED, commit('f')])
        self.assertIn('by Pat%0A::warning::fake <pat@example.org> has no', lines[0])
        self.assertFalse(any(line.startswith('::warning::') for line in lines))

    def test_percent_is_escaped_first(self):
        line, = self.offender_lines([commit('e', name='100%0A')])
        self.assertIn('by 100%250A <pat@example.org> has no', line)

    def test_carriage_return_in_email_is_escaped(self):
        line, = self.offender_lines([commit('e', email='pat@example.org\r::add-mask::x')])
        self.assertIn('by Pat Doe <pat@example.org%0D::add-mask::x> has no', line)

    def test_plain_author_is_unchanged(self):
        line, = self.offender_lines([commit('e', user={'login': 'patdoe'})])
        self.assertEqual(line, '::error::Commit eeeeeeeeeeee by Pat Doe <pat@example.org> has no matching '
                               '"Signed-off-by:" line. Add one with `git commit -s` (see CONTRIBUTING.md, '
                               '"Developer Certificate of Origin").')

    def assert_refused(self, commits, number):
        result = self.run_commits(commits)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stderr, f'::error::entry {number} is not a commit object\n')
        self.assertEqual(result.stdout, '')

    def test_non_text_author_fields_are_refused(self):
        broken = [commit('e', email=7), commit('e', name=['x']), commit('e', user={'login': 5}),
                  commit('e', user='mallory'), commit('e', user=['mallory']), commit('e', email={'a': 1})]
        for entry in broken:
            with self.subTest(entry=entry):
                # Numbering is 1-based after flattening slurped pages.
                self.assert_refused([[SIGNED], [SIGNED, entry]], 3)

    def test_shape_is_checked_before_exemption(self):
        owner = {'login': 'Grahammmm'}
        self.assertEqual(self.run_commits([commit('a', user=owner)]).returncode, 0)
        for entry in (commit('a', email=7, user=owner), commit('a', name=5, user=owner),
                      commit('a', email=7, user={'login': 'dependabot[bot]'})):
            with self.subTest(entry=entry):
                self.assert_refused([entry], 1)

    def test_null_and_absent_author_fields_are_accepted(self):
        absent = commit('e')
        del absent['author'], absent['commit']['author']['name']
        cases = [commit('e', email=None), commit('e', name=None), commit('e', user=None),
                 commit('e', user={'login': None}), commit('e', user={}), absent]
        for entry in cases:
            with self.subTest(entry=entry):
                self.assertEqual(self.run_commits([entry]).returncode, 1)
        result = self.run_commits([SIGNED, commit('d', user=None, message=SIGNED['commit']['message'])])
        self.assertEqual((result.returncode, result.stdout), (0, 'DCO check passed for 2 commit(s).\n'))


if __name__ == '__main__':
    unittest.main()

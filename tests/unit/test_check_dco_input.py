"""The DCO gate refuses an unreadable, empty or mis-shaped commit list with a named error."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from tests._support import ROOT

SCRIPT = ROOT / 'scripts/check_dco.py'


def commit(sha, email, message, login=None):
    return {'sha': sha * 40, 'author': {'login': login} if login else None,
            'commit': {'author': {'name': 'Pat Doe', 'email': email}, 'message': message}}


SIGNED = commit('d', 'pat@example.org', 'Fix typo\n\nSigned-off-by: Pat Doe <pat@example.org>', login='patdoe')
UNSIGNED = commit('e', 'pat@example.org', 'Fix typo', login='patdoe')
OWNER = commit('a', 'owner@example.com', 'Add feature', login='Grahammmm')


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


class DcoInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, content, name='commits.json'):
        path = Path(self.tmp.name, name)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content if isinstance(content, str) else json.dumps(content), encoding='utf-8')
        return path

    def assert_refused(self, result, message):
        self.assertEqual(result.returncode, 2, result.stderr)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertTrue(lines[0].startswith('::error::'), result.stderr)
        self.assertIn(message, lines[0])
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_empty_list_and_empty_slurp_are_refused(self):
        for content in ([], [[]], [[], []]):
            with self.subTest(content=content):
                self.assert_refused(run(self.write(content)),
                                    'commits.json holds no commits; refusing to pass an empty pull request')

    def test_missing_file_is_named(self):
        self.assert_refused(run(Path(self.tmp.name, 'absent.json')), 'cannot read absent.json (FileNotFoundError)')

    def test_directory_is_unreadable(self):
        self.assert_refused(run(self.tmp.name), 'cannot read ')

    def test_not_json_and_non_utf8_are_named(self):
        self.assert_refused(run(self.write('{')), 'commits.json is not JSON')
        self.assert_refused(run(self.write('')), 'commits.json is not JSON')
        self.assert_refused(run(self.write(b'\xff\xfe[]')), 'cannot read commits.json (UnicodeDecodeError)')

    def test_top_level_not_a_list_is_refused(self):
        for content in ({'sha': 'a' * 40}, 'null', '"text"', '7', [SIGNED, 'x'], [[SIGNED], 3]):
            with self.subTest(content=content):
                self.assert_refused(run(self.write(content)), 'commits.json is not a list of commits')

    def test_mis_shaped_entry_is_named_before_any_offender(self):
        no_author = json.loads(json.dumps(UNSIGNED))
        del no_author['commit']['author']
        self.assert_refused(run(self.write([UNSIGNED, no_author])), 'entry 2 is not a commit object')
        broken = [
            {}, [], {'sha': 'a' * 40}, {'sha': 7, 'commit': SIGNED['commit']},
            {'sha': 'a' * 40, 'commit': 'x'}, {'sha': 'a' * 40, 'commit': {'author': 'x', 'message': 'm'}},
            {'sha': 'a' * 40, 'commit': {'author': {}, 'message': None}},
        ]
        for entry in broken:
            with self.subTest(entry=entry):
                # Numbering is 1-based after flattening slurped pages.
                self.assert_refused(run(self.write([[SIGNED], [UNSIGNED, entry]])), 'entry 3 is not a commit object')

    def test_valid_input_behaves_as_before(self):
        ok = run(self.write([SIGNED]))
        self.assertEqual((ok.returncode, ok.stdout, ok.stderr), (0, 'DCO check passed for 1 commit(s).\n', ''))
        failed = run(self.write([UNSIGNED]))
        self.assertEqual(failed.returncode, 1)
        self.assertTrue(failed.stdout.startswith('::error::Commit eeeeeeeeeeee by Pat Doe <pat@example.org> has no'))
        self.assertEqual(run(self.write([OWNER])).returncode, 0)
        self.assertEqual(run('--fork', self.write([OWNER])).returncode, 1)
        self.assertEqual(run('--fork', self.write([SIGNED])).returncode, 0)

    def test_usage_still_exits_2(self):
        path = self.write([SIGNED])
        for args in ((), ('--fork',), (path, path)):
            with self.subTest(args=args):
                result = run(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr.strip(), 'Usage: python scripts/check_dco.py [--fork] commits.json')


if __name__ == '__main__':
    unittest.main()

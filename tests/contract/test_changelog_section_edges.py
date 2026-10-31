"""changelog_section names a doubled heading and an unreadable changelog."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from tests._support import ROOT


SCRIPT = ROOT / 'scripts/changelog_section.py'
_spec = importlib.util.spec_from_file_location('changelog_section_edges', SCRIPT)
changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog)

DOUBLED = '## 1.2.0 — 2026-10-01\n\n- First half.\n\n## 1.2.0 — 2026-10-01\n\n- Second half.\n'
PRERELEASE = '## 1.2.0 — 2026-10-02\n\n- Final.\n\n## 1.2.0-rc.1 — 2026-10-01\n\n- Candidate.\n'


def run(*args):
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, encoding='utf-8', env=env)


class ChangelogSectionEdgeTests(unittest.TestCase):
    def assert_one_error(self, result, needle):
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        errors = [line for line in result.stderr.splitlines() if line.startswith('::error::')]
        self.assertEqual(len(errors), 1, result.stderr)
        self.assertIn(needle, errors[0])

    def test_doubled_heading_is_refused(self):
        with self.assertRaisesRegex(LookupError, '2 sections for 1.2.0'):
            changelog.section(DOUBLED, 'v1.2.0')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'CHANGELOG.md')
            path.write_text(DOUBLED, encoding='utf-8')
            self.assert_one_error(run('v1.2.0', '--changelog', str(path)), '2 sections for 1.2.0; merge them')

    def test_prerelease_prefix_is_not_a_double(self):
        self.assertEqual(changelog.section(PRERELEASE, '1.2.0'), '- Final.')
        self.assertEqual(changelog.section(PRERELEASE, 'v1.2.0-rc.1'), '- Candidate.')

    def test_v_heading_matched_once(self):
        self.assertEqual(changelog.section('## v1.2.0\n\n- Only.\n\n## 1.1.0\n- Old.\n', '1.2.0'), '- Only.')
        with self.assertRaisesRegex(LookupError, '2 sections'):
            changelog.section('## v1.2.0\n- A.\n## 1.2.0\n- B.\n', '1.2.0')

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp, 'absent.md'))
            self.assert_one_error(run('v1.2.0', '--changelog', missing), f'cannot read {missing} (FileNotFoundError)')

    def test_folder_as_changelog(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run('v1.2.0', '--changelog', tmp)
        self.assert_one_error(result, f'cannot read {tmp} (IsADirectoryError)')

    def test_non_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'CHANGELOG.md')
            path.write_bytes(b'## 1.2.0\n\n- caf\xe9\n')
            self.assert_one_error(run('v1.2.0', '--changelog', str(path)), f'{path} is not UTF-8')

    def test_real_changelog_newest_release_unchanged(self):
        text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        match = re.search(r'^## (\d+\.\d+\.\d+)(?:\s.*)?$', text, re.M)
        assert match is not None, 'CHANGELOG.md has no released version'
        version = match.group(1)
        # The pre-change rule: the lines after the heading up to the next "## ".
        expected = text[match.end():].split('\n## ', 1)[0].strip()
        self.assertTrue(expected)
        self.assertEqual(changelog.section(text, version), expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'CHANGELOG.md')
            path.write_text(text, encoding='utf-8')
            result = run(f'v{version}', '--changelog', str(path))
            bad = run('1.2', '--changelog', str(path))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected + '\n', ''))
        self.assert_one_error(bad, 'Not a release version: 1.2')


if __name__ == '__main__':
    unittest.main()

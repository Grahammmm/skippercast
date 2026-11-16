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


    def test_combined_prerelease_build_version(self):
        text = ('## 1.2.0 — 2026-10-05\n\n- Final.\n\n## 1.2.0-rc.1+build.7 — 2026-10-04\n\n- Combined.\n\n### Internal\n\n- Detail.\n\n'
                '## 1.2.0-rc.1 — 2026-10-03\n\n- Pre.\n\n## 1.2.0+build.7 — 2026-10-02\n\n- Meta.\n')
        expected = '- Combined.\n\n### Internal\n\n- Detail.'
        self.assertEqual(changelog.section(text, '1.2.0-rc.1+build.7'), expected)
        self.assertEqual(changelog.section(text, 'v1.2.0-rc.1+build.7'), expected)
        self.assertEqual(changelog.section(text.replace('## 1.2.0-rc.1+', '## v1.2.0-rc.1+'), '1.2.0-rc.1+build.7'), expected)
        self.assertEqual(changelog.section(text, '1.2.0-rc.1'), '- Pre.')
        self.assertEqual(changelog.section(text, '1.2.0+build.7'), '- Meta.')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'CHANGELOG.md')
            path.write_text(text, encoding='utf-8')
            result = run('v1.2.0-rc.1+build.7', '--changelog', str(path))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected + '\n', ''))

    def test_combined_version_identity_is_exact(self):
        text = ''.join(f'## 1.2.0-rc.1{suffix} — 2026-10-01\n\n- Body {suffix or "plain"}.\n\n'
                       for suffix in ('+build.7', '+build.70', '+build.8', ''))
        for suffix in ('+build.7', '+build.70', '+build.8', ''):
            self.assertEqual(changelog.section(text, f'1.2.0-rc.1{suffix}'), f'- Body {suffix or "plain"}.')
        for missing in ('1.2.0-rc.1+build.9', '1.2.0-rc.1+buildx7', '1.2.0-rc.1+build7'):
            with self.assertRaisesRegex(LookupError, 'No CHANGELOG section'):
                changelog.section(text, missing)

    def test_combined_version_refuses_duplicate_or_empty(self):
        doubled = '## 1.2.0-rc.1+build.7\n- A.\n\n## v1.2.0-rc.1+build.7\n- B.\n'
        with self.assertRaisesRegex(LookupError, '2 sections for 1.2.0-rc.1\\+build.7'):
            changelog.section(doubled, '1.2.0-rc.1+build.7')
        with self.assertRaisesRegex(LookupError, 'No CHANGELOG section for 1.2.0-rc.1\\+build.7'):
            changelog.section('## 1.2.0-rc.1+build.7\n\n## 1.1.0\n- Old.\n', '1.2.0-rc.1+build.7')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'CHANGELOG.md')
            path.write_text(doubled, encoding='utf-8')
            self.assert_one_error(run('1.2.0-rc.1+build.7', '--changelog', str(path)), '2 sections for 1.2.0-rc.1+build.7; merge them')

    def test_combined_version_fenced_examples_are_not_duplicates(self):
        text = '## 1.2.0-rc.1+build.7\n\n```md\n## 1.2.0-rc.1+build.7\n- Example.\n```\n\n- Real.\n'
        self.assertEqual(changelog.section(text, '1.2.0-rc.1+build.7'), '```md\n## 1.2.0-rc.1+build.7\n- Example.\n```\n\n- Real.')

    def test_combined_suffix_malformed_inputs(self):
        for bad in ('', '1.2', '1.2.0-rc.1+', '1.2.0-rc.1++build.7', '1.2.0+build.7+extra'):
            with self.assertRaisesRegex(ValueError, 'Not a release version'):
                changelog.section('## 1.2.0\n- A.\n', bad)
        result = run('1.2.0-rc.1++build.7')
        self.assert_one_error(result, 'Not a release version: 1.2.0-rc.1++build.7')


if __name__ == '__main__':
    unittest.main()

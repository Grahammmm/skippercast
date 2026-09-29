"""Release notes come from the matching CHANGELOG section."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('changelog_section', ROOT / 'scripts/changelog_section.py')
changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog)

SAMPLE = """# Changelog

## Unreleased

- Pending change.

## 1.2.0 — 2026-10-01

- User-facing line.

### Internal

- Internal line.

## 1.1.0 — 2026-09-01

- Older line.
"""


class ChangelogSectionTests(unittest.TestCase):
    def test_extracts_section_with_internal_subsection(self):
        notes = changelog.section(SAMPLE, 'v1.2.0')
        self.assertEqual(notes, '- User-facing line.\n\n### Internal\n\n- Internal line.')

    def test_accepts_bare_version_and_last_section(self):
        self.assertEqual(changelog.section(SAMPLE, '1.1.0'), '- Older line.')

    def test_prefix_versions_do_not_match(self):
        with self.assertRaises(LookupError):
            changelog.section(SAMPLE, '1.2.1')

    def test_rejects_non_versions_and_unreleased(self):
        for bad in ('Unreleased', 'v1.2', 'latest'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                changelog.section(SAMPLE, bad)

    def test_empty_section_fails(self):
        with self.assertRaises(LookupError):
            changelog.section('## 2.0.0 — 2026-11-01\n\n## 1.0.0\n- x\n', '2.0.0')

    def test_repository_changelog_has_current_release(self):
        text = (ROOT / 'CHANGELOG.md').read_text()
        self.assertIn('Direct single-spot GPX downloads', changelog.section(text, 'v0.3.0'))

    def test_unreleased_separates_internal_changes(self):
        text = (ROOT / 'CHANGELOG.md').read_text()
        unreleased = text.split('## Unreleased', 1)[1].split('\n## ', 1)[0]
        self.assertEqual(unreleased.count('### Internal'), 1)
        user_facing = unreleased.split('### Internal')[0]
        self.assertTrue(any(line.startswith('- ') for line in user_facing.splitlines()))

    def test_cli_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'CHANGELOG.md')
            path.write_text(SAMPLE)
            script = str(ROOT / 'scripts/changelog_section.py')
            ok = subprocess.run([sys.executable, script, 'v1.2.0', '--changelog', str(path)], capture_output=True, text=True)
            missing = subprocess.run([sys.executable, script, 'v9.9.9', '--changelog', str(path)], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0)
        self.assertTrue(ok.stdout.startswith('- User-facing line.'))
        self.assertEqual(missing.returncode, 1)
        self.assertIn('No CHANGELOG section', missing.stderr)


if __name__ == '__main__':
    unittest.main()

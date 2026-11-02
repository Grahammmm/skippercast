"""changelog_section treats lines inside code fences as text and refuses an unclosed fence."""
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
_spec = importlib.util.spec_from_file_location('changelog_section_fences', SCRIPT)
changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog)

USAGE = ('## 1.2.0 — 2026-10-02\n\n- Docs.\n\n```md\n## Usage\n\nRun it.\n```\n\n- After the block.\n\n'
         '## 1.1.0 — 2026-10-01\n\n- Older.\n')
EXAMPLE = '## 1.2.0 — 2026-10-02\n\n- New.\n\n## 1.1.0 — 2026-10-01\n\n- Old.\n\n```\n## 1.2.0 — example\n```\n'
UNCLOSED = '## 1.2.0 — 2026-10-02\n\n- New.\n\n## 1.1.0 — 2026-10-01\n\n```\n## 1.0.0\n'


def run(*args):
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, encoding='utf-8', env=env)


def main_notes(text, version):
    """The notes main produced before fences were recognised (no fence handling at all)."""
    heading = re.compile(r'^## v?' + re.escape(version) + r'(?:\s|$)')
    body, inside = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            if inside:
                break
            inside = bool(heading.match(line))
            continue
        if inside:
            body.append(line)
    return '\n'.join(body).strip()


class ChangelogSectionFenceTests(unittest.TestCase):
    def test_heading_inside_fence_neither_ends_nor_starts_a_section(self):
        notes = changelog.section(USAGE, 'v1.2.0')
        self.assertIn('```md\n## Usage\n\nRun it.\n```', notes)
        self.assertTrue(notes.endswith('- After the block.'))
        self.assertNotIn('Older', notes)
        with self.assertRaisesRegex(LookupError, 'No CHANGELOG section for 9.9.9'):
            changelog.section(USAGE.replace('Usage', '9.9.9'), '9.9.9')

    def test_fenced_version_example_is_not_a_doubled_heading(self):
        self.assertEqual(changelog.section(EXAMPLE, '1.2.0'), '- New.')
        self.assertEqual(changelog.section(EXAMPLE, '1.1.0'), '- Old.\n\n```\n## 1.2.0 — example\n```')

    def test_tilde_long_and_indented_fences(self):
        tilde = '## 1.2.0\n\n~~~\n## 1.1.0\n~~~\n- Tail.\n\n## 1.1.0\n\n- Old.\n'
        self.assertEqual(changelog.section(tilde, '1.2.0'), '~~~\n## 1.1.0\n~~~\n- Tail.')
        four = '## 1.2.0\n\n````\n```\n## 1.1.0\n```\n````\n- Tail.\n\n## 1.1.0\n\n- Old.\n'
        self.assertEqual(changelog.section(four, '1.2.0'), '````\n```\n## 1.1.0\n```\n````\n- Tail.')
        three = '## 1.2.0\n\n   ```\n## 1.1.0\n   ```\n- Tail.\n\n## 1.1.0\n\n- Old.\n'
        self.assertEqual(changelog.section(three, '1.2.0'), '```\n## 1.1.0\n   ```\n- Tail.')
        self.assertEqual(changelog.fenced_lines(['    ```', '## 1.1.0']), [False, False])
        indented = '## 1.2.0\n\n- New.\n\n    ```\n\n## 1.1.0\n\n- Old.\n'
        self.assertEqual(changelog.section(indented, '1.2.0'), '- New.\n\n    ```')
        self.assertEqual(changelog.section(indented, '1.1.0'), '- Old.')
        with self.assertRaisesRegex(LookupError, 'unclosed code fence at line 3'):
            changelog.section('## 1.2.0\n\n~~~\n## 1.1.0\n```\n', '1.2.0')

    def test_unclosed_fence_in_earlier_section_exits_one_by_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'CHANGELOG.md')
            path.write_text(UNCLOSED, encoding='utf-8')
            result = run('v1.2.0', '--changelog', str(path))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(result.stderr.splitlines(), ['::error::CHANGELOG has an unclosed code fence at line 7'])

    def test_backtick_info_string_with_backtick_is_not_a_fence(self):
        text = '## 1.2.0\n\n``` a`b\n\n## 1.1.0\n\n- Old.\n'
        self.assertEqual(changelog.section(text, '1.2.0'), '``` a`b')
        self.assertEqual(changelog.section(text, '1.1.0'), '- Old.')
        self.assertEqual(changelog.section('## 1.2.0\n\n~~~ a`b\n## 1.1.0\n~~~\n', '1.2.0'), '~~~ a`b\n## 1.1.0\n~~~')

    def test_real_changelog_notes_match_main_for_every_heading(self):
        text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        versions = re.findall(r'^## v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)(?:\s|$)', text, re.M)
        self.assertGreater(len(versions), 0)
        for version in versions:
            with self.subTest(version=version):
                self.assertEqual(changelog.section(text, version), main_notes(text, version))


if __name__ == '__main__':
    unittest.main()

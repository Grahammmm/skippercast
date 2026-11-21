"""Replay release-note preparation on local tags, with a file as the release sink."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests._support import ROOT

TAG = 'v1.2.3'
TAGGED = '## 1.2.3\n\n- Tagged notes.\n\n### Internal\n\n- Tagged detail.\n'
BRANCH = '## 1.2.3\n\n- Notes edited after tagging.\n'


def replay(work, changelog, *, version='1.2.3', tag_kind: str | None = 'annotated'):
    def git(*args):
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                        '-c', 'commit.gpgsign=false', '-c', 'tag.gpgSign=false', *args],
                       cwd=work, check=True, capture_output=True)

    git('init', '--initial-branch', TAG)
    (work / 'package.json').write_text(json.dumps({'version': version}), encoding='utf-8')
    if changelog is not None:
        (work / 'CHANGELOG.md').write_text(changelog, encoding='utf-8')
    parser = work / 'scripts' / 'changelog_section.py'
    parser.parent.mkdir()
    parser.write_text('raise SystemExit("historical parser must not run")\n', encoding='utf-8')
    git('add', '.')
    git('commit', '-m', 'Historical fixture')
    if tag_kind == 'annotated':
        git('tag', '-a', TAG, '-m', 'Fixture tag')
    elif tag_kind == 'lightweight':
        git('tag', TAG)

    shutil.copyfile(ROOT / 'scripts/changelog_section.py', parser)
    (work / 'package.json').write_text('{"version":"1.2.3"}', encoding='utf-8')
    (work / 'CHANGELOG.md').write_text(BRANCH, encoding='utf-8')
    git('add', '.')
    git('commit', '-m', 'Dispatch checkout fixture')

    workflow = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
    notes_step = workflow.split('- name: Release notes from CHANGELOG.md\n', 1)[1].split('\n      - ', 1)[0]
    command = re.search(r'^        run: (.+)$', notes_step, re.MULTILINE)
    assert command is not None, 'Expected a release-note preparation command'
    runner_temp = work / 'runner-temp'
    runner_temp.mkdir()
    # Bash stops on a failed notes step, as Actions does. Only the inert copy
    # consumes the result: neither this script nor the fixture calls GitHub.
    runner = work / 'replay.sh'
    runner.write_text(command[1] + '\ncp "$RUNNER_TEMP/notes.md" "$RUNNER_TEMP/release-sink.md"\n', encoding='utf-8')
    result = subprocess.run(['bash', '-e', str(runner)], cwd=work, capture_output=True, text=True,
                            env={**os.environ, 'TAG': TAG, 'RUNNER_TEMP': str(runner_temp)})
    sink = runner_temp / 'release-sink.md'
    return result, sink.read_text(encoding='utf-8') if sink.exists() else None


class TaggedReleaseNotesTests(unittest.TestCase):
    def test_uses_tagged_notes_with_parser_from_dispatch_checkout(self):
        for tag_kind in ('annotated', 'lightweight'):
            with self.subTest(tag_kind=tag_kind), tempfile.TemporaryDirectory() as tmp:
                result, notes = replay(Path(tmp), TAGGED, tag_kind=tag_kind)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(notes, '- Tagged notes.\n\n### Internal\n\n- Tagged detail.\n')

    def test_unusable_historical_notes_stop_before_release_sink(self):
        for changelog, error in (
            ('## 1.2.2\n- Other version.\n', 'No CHANGELOG section for 1.2.3'),
            (TAGGED + '\n## v1.2.3\n- Duplicate.\n', '2 sections for 1.2.3'),
            (None, 'Cannot read CHANGELOG.md at tag v1.2.3'),
        ):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                result, notes = replay(Path(tmp), changelog)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(error, result.stderr)
                self.assertIsNone(notes)

    def test_branch_never_substitutes_for_tag_or_tagged_package_version(self):
        for version, tag_kind, error in (
            ('1.2.2', 'annotated', 'different package.json version'),
            ('1.2.3', None, 'does not resolve to a commit'),
        ):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                result, notes = replay(Path(tmp), TAGGED, version=version, tag_kind=tag_kind)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(error, result.stderr)
                self.assertIsNone(notes)

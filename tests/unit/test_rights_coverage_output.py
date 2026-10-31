"""RF1220-4: the coverage output folder holds both files or does not exist, and a retry works."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.coast_diagnostics import rights_coverage as coverage
from tests._support import ROOT


class RightsCoverageOutputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='rf1220-4-'))
        (self.root / 'catalog').mkdir()
        row = json.loads((ROOT / 'tests/fixtures/n3_rights_coverage/federal.json').read_text())
        (self.root / 'catalog/sources.json').write_text(json.dumps({'sources': [row]}))
        self.recipe = self.root / 'recipe.json'
        self.recipe.write_text(json.dumps({'sources': ['federal']}))
        self.parent = self.root / 'out'
        self.parent.mkdir()
        self.output = self.parent / 'coverage-run'
        self.target = self.root / 'target'
        self.target.mkdir()

    def run_main(self, output=None):
        argv = ['--repo-root', str(self.root), '--recipe', str(self.recipe),
                '--output-root', str(output or self.output)]
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = coverage.main(argv)
        return code, stdout.getvalue()

    def temp_siblings(self, parent=None):
        return sorted(p.name for p in (parent or self.parent).iterdir() if p.name.startswith('.'))

    def assert_failed_clean(self, code, stdout, kind):
        self.assertEqual(code, 2)
        self.assertEqual(stdout.splitlines(), [stdout.strip()], 'only the INPUT_ERROR line is printed')
        self.assertTrue(stdout.startswith('INPUT_ERROR ' + kind + ': '), stdout)
        self.assertFalse(self.output.exists(), 'no half output folder')
        self.assertEqual(self.temp_siblings(), [], 'no temp sibling remains')
        self.assertEqual(list(self.parent.rglob('coverage.json')), [])

    def test_happy_path_same_bytes_no_temp(self):
        report = coverage.check_coverage(self.root, self.recipe)
        code, stdout = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual((self.output / 'coverage.json').read_text(encoding='utf-8'),
                         json.dumps(report, indent=2, sort_keys=True) + '\n')
        self.assertEqual((self.output / 'coverage.txt').read_text(encoding='utf-8'), coverage.render_table(report))
        self.assertEqual(stdout, coverage.render_table(report))
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ['coverage.json', 'coverage.txt'])
        self.assertEqual(self.temp_siblings(), [])

    def test_render_failure_leaves_nothing_and_retry_works(self):
        with patch.object(coverage, 'render_table', side_effect=ValueError('render broke')):
            code, stdout = self.run_main()
        self.assert_failed_clean(code, stdout, 'ValueError')
        code, stdout = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn('Verdict: COMPLETE', stdout)

    def test_second_write_failure_leaves_nothing_and_retry_works(self):
        real = Path.write_text

        def failing(path, *args, **kwargs):
            if path.name == 'coverage.txt':
                raise OSError('disk full')
            return real(path, *args, **kwargs)
        with patch.object(Path, 'write_text', failing):
            code, stdout = self.run_main()
        self.assert_failed_clean(code, stdout, 'OSError')
        self.assertEqual(self.run_main()[0], 0)

    def test_rename_failure_leaves_nothing(self):
        with patch.object(coverage.os, 'rename', side_effect=OSError('rename refused')):
            code, stdout = self.run_main()
        self.assert_failed_clean(code, stdout, 'OSError')

    def test_existing_output_still_refused_unchanged(self):
        for contents in ({}, {'keep.txt': 'mine'}):
            with self.subTest(contents=contents):
                output = self.parent / ('run-' + str(len(contents)))
                output.mkdir()
                for name, text in contents.items():
                    (output / name).write_text(text)
                code, stdout = self.run_main(output)
                self.assertEqual(code, 2)
                self.assertIn('must be new', stdout)
                self.assertEqual({p.name: p.read_text() for p in output.iterdir()}, contents)
                self.assertEqual(self.temp_siblings(), [])

    def test_symlinked_parent_refused_without_temp_in_target(self):
        (self.root / 'alias').symlink_to(self.target, target_is_directory=True)
        code, stdout = self.run_main(self.root / 'alias' / 'run')
        self.assertEqual(code, 2)
        self.assertIn('Symlink', stdout)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_parent_swapped_to_symlink_after_render_refused(self):
        output = self.root / 'late' / 'run'
        real = coverage.render_table

        def swap(report):
            (self.root / 'late').symlink_to(self.target, target_is_directory=True)
            return real(report)
        with patch.object(coverage, 'render_table', side_effect=swap):
            code, stdout = self.run_main(output)
        self.assertEqual(code, 2)
        self.assertTrue(stdout.startswith('INPUT_ERROR ValueError: Symlink'), stdout)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_missing_parent_chain_created(self):
        output = self.root / 'fresh' / 'deeper' / 'run'
        self.assertEqual(self.run_main(output)[0], 0)
        self.assertEqual(sorted(p.name for p in output.iterdir()), ['coverage.json', 'coverage.txt'])
        self.assertEqual(self.temp_siblings(output.parent), [])

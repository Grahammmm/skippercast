import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.report_regulations import report
from tests._support import ROOT as REPO
from tests.unit.test_report_regulations import A_SECTION, health, make_root, section

SCRIPT = REPO / 'scripts' / 'report_regulations.py'
HEADER = '## Regulation coverage\n\n'


def report_recording_reads(root):
    reads, original = [], Path.read_text

    def recording(path, *args, **kwargs):
        reads.append(Path(os.path.relpath(path, root)).as_posix())
        return original(path, *args, **kwargs)

    with mock.patch.object(Path, 'read_text', recording):
        return report(root), reads


class RegionIdTests(unittest.TestCase):
    def test_path_escaping_id_is_never_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {'a': health()}, index=[{'region_id': 'a'}, {'region_id': '../outside'}])
            (root / 'outside').mkdir()
            (root / 'outside/regulations-health.json').write_text(json.dumps(health(jurisdiction_id='OUTSIDE-MARKER')))
            (markdown, attention, unreadable), reads = report_recording_reads(root)
        self.assertEqual(reads, ['regions/index.json', 'regions/a/regulations-health.json'])
        self.assertNotIn('OUTSIDE-MARKER', markdown)
        self.assertNotIn('outside', markdown)
        self.assertEqual(markdown, HEADER + A_SECTION)
        self.assertTrue(attention)
        self.assertEqual(unreadable, ['1'])

    def test_non_plain_ids_are_recorded_by_position_and_never_printed(self):
        for bad in ['', '/abs', 'a/b', '.hidden', 'a\nb', 'x' * 65, '..', 'a b', '-a', 'a\x00']:
            with self.subTest(repr(bad)), tempfile.TemporaryDirectory() as tmp:
                root = make_root(tmp, {'a': health()}, index=[{'region_id': 'a'}, {'region_id': bad}])
                (root / 'regions/regulations-health.json').write_text('{')
                (markdown, _, unreadable), reads = report_recording_reads(root)
                self.assertEqual(reads, ['regions/index.json', 'regions/a/regulations-health.json'])
                self.assertEqual(markdown, HEADER + A_SECTION)
                self.assertEqual(unreadable, ['1'])

    def test_longest_plain_and_upper_case_ids_still_read(self):
        ids = ['CA', 'OR', 'morro-bay', 'big_sur', 'x' * 64]
        with tempfile.TemporaryDirectory() as tmp:
            markdown, _, unreadable = report(make_root(tmp, {ident: health() for ident in ids}))
        self.assertEqual(unreadable, [])
        for ident in ids:
            self.assertEqual(section(markdown, ident), A_SECTION.replace('### a\n', f'### {ident}\n'))

    def test_good_index_output_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(report(make_root(tmp, {'a': health()})), (HEADER + A_SECTION, True, []))

    def test_id_listed_twice_is_reported_once_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {'a': health()}, index=[{'region_id': 'a'}, {'region_id': 'a'}])
            (markdown, attention, unreadable), reads = report_recording_reads(root)
        self.assertEqual(reads.count('regions/a/regulations-health.json'), 1)
        self.assertEqual(markdown, HEADER + A_SECTION
                         + '### a\nregions/index.json lists a more than once; reported once.\n\n')
        self.assertTrue(attention)
        self.assertEqual(unreadable, ['a (listed twice)'])

    def test_third_listing_and_missing_duplicate_each_named(self):
        index = [{'region_id': 'b'}, {'region_id': 'a'}, {'region_id': 'b'}, {'region_id': 'a'}, {'region_id': 'a'}]
        with tempfile.TemporaryDirectory() as tmp:
            markdown, _, unreadable = report(make_root(tmp, {'a': health(), 'b': None}, index=index))
        self.assertEqual(unreadable, ['b', 'b (listed twice)', 'a (listed twice)', 'a (listed twice)'])
        self.assertEqual(markdown.count('Jurisdiction: '), 1)
        self.assertEqual(markdown.count('more than once; reported once.'), 3)


class RegionIdMainTests(unittest.TestCase):
    def test_duplicate_fails_the_step_with_one_error_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {'a': health()}, index=[{'region_id': 'a'}, {'region_id': 'a'}])
            summary = Path(tmp) / 'summary.md'
            result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root)], capture_output=True, text=True,
                                    env={**os.environ, 'GITHUB_STEP_SUMMARY': str(summary)}, cwd=REPO, check=False)
            summary_text = summary.read_text()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], '::error::Regulation health unreadable for: a (listed twice)')
        self.assertEqual(result.stdout.count('::error::'), 1)
        self.assertIn('regions/index.json lists a more than once; reported once.', summary_text)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()

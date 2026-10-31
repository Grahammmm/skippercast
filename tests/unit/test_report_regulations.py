import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.report_regulations import _region_lines, report
from tests._support import ROOT as REPO

SCRIPT = REPO / 'scripts' / 'report_regulations.py'


def health(**changes):
    data = {'rules_review_status': 'reviewed', 'valid_for_current_date': True, 'jurisdiction_id': 'us-ca',
            'reviewed_at': '2026-10-01', 'valid_through': '2026-12-31',
            'species': {'ling': {'name': 'Lingcod', 'issues': []}},
            'areas': {'a1': {'name': 'Area 1', 'issues': ['closed']}},
            'checks': {'s1': {'status': 'match', 'source_status': 'ok', 'checked_at': '2026-10-30'},
                       's2': {'status': 'changed', 'source_status': 'ok'}},
            'review_required': ['s2']}
    data.update(changes)
    return data


def make_root(tmp, regions, index=None):
    root = Path(tmp)
    (root / 'regions').mkdir()
    entries = index if index is not None else [{'region_id': ident} for ident in regions]
    (root / 'regions/index.json').write_text(json.dumps({'regions': entries}))
    for ident, data in regions.items():
        if data is None:
            continue
        (root / 'regions' / ident).mkdir()
        text = data if isinstance(data, str) else json.dumps(data)
        (root / 'regions' / ident / 'regulations-health.json').write_text(text)
    return root


def section(markdown, ident):
    start = markdown.index(f'### {ident}\n')
    end = markdown.find('\n### ', start)
    return markdown[start:] if end == -1 else markdown[start:end + 1]


A_SECTION = ('### a\nJurisdiction: us-ca · reviewed 2026-10-01 · valid through 2026-12-31\n'
             'Required sources: 1/2 match; legal content: reviewed; review valid for today: True.\n'
             'Species requiring review or a fresh check: none\nArea notices requiring a fresh rule check: Area 1\n'
             'Source review is not live military, harbor or entrance clearance.\n\n- s2: changed · ok · checked None\n')


class ReportTests(unittest.TestCase):
    def test_two_good_regions_match_the_per_region_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            good_b = health(review_required=[], areas={})
            markdown, attention, unreadable = report(make_root(tmp, {'a': health(), 'b': good_b}))
        expected = ['## Regulation coverage', ''] + _region_lines('a', health())[0] + _region_lines('b', good_b)[0]
        self.assertEqual(markdown, '\n'.join(expected) + '\n')
        self.assertEqual(section(markdown, 'a'), A_SECTION)
        self.assertTrue(attention)
        self.assertEqual(unreadable, [])

    def test_missing_health_file_is_named_and_others_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown, attention, unreadable = report(make_root(tmp, {'b': None, 'a': health(review_required=[], areas={})}))
        self.assertEqual(section(markdown, 'b'),
                         "### b\nregulations-health.json missing; this region's rules were not checked.\n\n")
        self.assertIn('Required sources: 2/2 match', section(markdown, 'a'))
        self.assertTrue(attention)
        self.assertEqual(unreadable, ['b'])

    def test_unreadable_health_file_is_named_without_partial_lines(self):
        cases = {'not json': ('{', 'JSONDecodeError'),
                 'checks absent': ({k: v for k, v in health().items() if k != 'checks'}, "KeyError: 'checks'"),
                 'species is a list': (health(species=[]), 'AttributeError'),
                 'review source absent': (health(review_required=['s9']), "KeyError: 's9'"),
                 'not utf-8': (None, 'UnicodeDecodeError')}
        for name, (data, reason) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = make_root(tmp, {'a': health(), 'b': data or {}})
                if data is None:
                    (root / 'regions/b/regulations-health.json').write_bytes(b'\xff\xfe\x00')
                markdown, attention, unreadable = report(root)
                lines = section(markdown, 'b').split('\n')
                self.assertEqual(len(lines), 4, lines)
                self.assertTrue(lines[1].startswith(f'regulations-health.json unreadable ({reason}'), lines[1])
                self.assertTrue(lines[1].endswith("); this region's rules were not checked."), lines[1])
                self.assertEqual(section(markdown, 'a'), A_SECTION)
                self.assertTrue(attention)
                self.assertEqual(unreadable, ['b'])

    def test_unreadable_reason_is_capped_at_120_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown, _, _ = report(make_root(tmp, {'b': health(review_required=['x' * 300])}))
        self.assertIn(f"(KeyError: '{'x' * 119}); this", markdown)

    def test_unreadable_index_stops_with_one_line(self):
        for name, text in {'absent': None, 'not json': '[', 'no regions key': '{}',
                           'regions not a list': '{"regions": {}}', 'index is a list': '[]'}.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / 'regions').mkdir()
                if text is not None:
                    (Path(tmp) / 'regions/index.json').write_text(text)
                with self.assertRaises(SystemExit) as caught:
                    report(Path(tmp))
                self.assertTrue(str(caught.exception.code).startswith('regions/index.json unreadable: '))

    def test_index_entry_without_region_id_is_skipped_and_reported(self):
        index = [{'region_id': 'a'}, {'name': 'no id'}, 'b', {'region_id': 7}]
        with tempfile.TemporaryDirectory() as tmp:
            markdown, attention, unreadable = report(make_root(tmp, {'a': health()}, index=index))
        self.assertEqual(section(markdown, 'a'), A_SECTION)
        self.assertEqual(markdown.count('### '), 1)
        self.assertTrue(attention)
        self.assertEqual(unreadable, ['1', '2', '3'])


class MainTests(unittest.TestCase):
    def run_main(self, tmp, regions, index=None):
        root = make_root(tmp, regions, index)
        summary = Path(tmp) / 'summary.md'
        env = {**os.environ, 'GITHUB_STEP_SUMMARY': str(summary)}
        result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root)], capture_output=True, text=True,
                                env=env, cwd=REPO, check=False)
        return result, summary.read_text() if summary.exists() else ''

    def test_bad_region_fails_after_the_summary_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, summary = self.run_main(tmp, {'a': health(), 'b': '{', 'c': None})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], '::error::Regulation health unreadable for: b, c')
        self.assertLess(result.stdout.index('### a'), result.stdout.index('::error::'))
        self.assertIn(A_SECTION, summary)
        self.assertIn('### c\nregulations-health.json missing', summary)
        self.assertNotIn('Traceback', result.stderr)

    def test_all_good_regions_exit_zero_without_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, summary = self.run_main(tmp, {'a': health()})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('::error::', result.stdout)
        self.assertIn('::warning::', result.stdout)
        self.assertIn(A_SECTION, summary)

    def test_unreadable_index_exits_one_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self.run_main(tmp, {}, index={'bad': 1})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.strip(), 'regions/index.json unreadable: TypeError')

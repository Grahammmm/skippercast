import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import report_regulations as rr
from tests._support import ROOT as REPO
from tests.unit.test_report_regulations import A_SECTION, health, make_root, section

SCRIPT = REPO / 'scripts' / 'report_regulations.py'
DIGITS = getattr(sys, 'get_int_max_str_digits', lambda: 0)()
BIG_INT = '{"unused":' + '1' * (DIGITS + 700) + '}' if DIGITS > 0 else None
DEEP = '[' * 100000 + '0' + ']' * 100000
BAD_MARK = 'DECODE-LIMIT-MARK'


def failing_loads(exc):
    real = json.loads

    def loads(text, *args, **kwargs):
        if BAD_MARK in text:
            raise exc
        return real(text, *args, **kwargs)
    return loads


def run_cli(root, summary):
    env = dict(os.environ, GITHUB_STEP_SUMMARY=str(summary))
    return subprocess.run([sys.executable, '-B', str(SCRIPT), '--root', str(root)],
                          capture_output=True, text=True, env=env, cwd=REPO)


class SeamTests(unittest.TestCase):
    def regions(self, order):
        bad = health(note=BAD_MARK)
        return {ident: (bad if ident == 'b' else health()) for ident in order}

    def test_regional_decoder_refusals_continue_with_neighbours(self):
        for exc in (ValueError('x' * 300), RecursionError('deep')):
            for order in (['b', 'a'], ['a', 'b', 'c']):
                with self.subTest(exc=type(exc).__name__, order=order), tempfile.TemporaryDirectory() as tmp:
                    root = make_root(tmp, self.regions(order))
                    with mock.patch.object(rr.json, 'loads', failing_loads(exc)):
                        markdown, attention, unreadable = rr.report(root)
                    self.assertTrue(attention)
                    self.assertEqual(unreadable, ['b'])
                    self.assertEqual(section(markdown, 'a'), A_SECTION)
                    self.assertEqual(markdown.count('### b\n'), 1)
                    self.assertIn(f'unreadable ({type(exc).__name__}: ', markdown)
                    self.assertNotIn('x' * 121, markdown)
                    self.assertNotIn('Jurisdiction', section(markdown, 'b'))
                    if 'c' in order:
                        self.assertEqual(section(markdown, 'c'), A_SECTION.replace('### a', '### c'))

    def test_index_decoder_refusals_exit_with_one_line(self):
        for exc in (ValueError('x'), RecursionError('deep')):
            with self.subTest(exc=type(exc).__name__), tempfile.TemporaryDirectory() as tmp:
                root = make_root(tmp, {'a': health()})
                (root / 'regions/index.json').write_text(json.dumps({'regions': [{'region_id': 'a'}], 'm': BAD_MARK}))
                with mock.patch.object(rr.json, 'loads', failing_loads(exc)), \
                        self.assertRaises(SystemExit) as caught:
                    rr.report(root)
                self.assertEqual(str(caught.exception), f'regions/index.json unreadable: {type(exc).__name__}')
                self.assertTrue(caught.exception.__suppress_context__)

    def test_healthy_control_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown, attention, unreadable = rr.report(make_root(tmp, {'a': health()}))
        self.assertEqual(section(markdown, 'a'), A_SECTION)
        self.assertEqual((attention, unreadable), (True, []))


class RealCliTests(unittest.TestCase):
    def bad_health_case(self, payload, expected):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {'b': payload, 'a': health()}, index=[{'region_id': 'b'}, {'region_id': 'a'}])
            summary = Path(tmp) / 'summary.md'
            summary.write_text('PRIOR\n')
            before = (root / 'regions/b/regulations-health.json').read_bytes()
            result = run_cli(root, summary)
            self.assertEqual(result.returncode, 1, result.stderr[-300:])
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(result.stdout.count('::error::Regulation health unreadable for: b\n'), 1)
            self.assertIn('::warning::', result.stdout)
            self.assertIn(A_SECTION, result.stdout)
            text = summary.read_text()
            self.assertTrue(text.startswith('PRIOR\n'))
            self.assertIn(A_SECTION, text)
            self.assertIn(f'unreadable ({expected}: ', text)
            self.assertEqual((root / 'regions/b/regulations-health.json').read_bytes(), before)

    @unittest.skipIf(BIG_INT is None, 'integer digit cap disabled; real guard not applicable')
    def test_oversized_integer_health(self):
        self.bad_health_case(BIG_INT, 'ValueError')

    def test_deep_array_health(self):
        self.bad_health_case(DEEP, 'RecursionError')

    def bad_index_case(self, payload, name):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {'a': health()})
            (root / 'regions/index.json').write_text(payload)
            summary = Path(tmp) / 'summary.md'
            result = run_cli(root, summary)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, f'regions/index.json unreadable: {name}\n')
            self.assertEqual(result.stdout, '')
            self.assertFalse(summary.exists())

    @unittest.skipIf(BIG_INT is None, 'integer digit cap disabled; real guard not applicable')
    def test_oversized_integer_index(self):
        self.bad_index_case(BIG_INT, 'ValueError')

    def test_deep_array_index(self):
        self.bad_index_case(DEEP, 'RecursionError')


if __name__ == '__main__':
    unittest.main()

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.report_regulations import _region_lines, report
from tests._support import ROOT as REPO
from tests.unit.test_report_regulations import A_SECTION, health, make_root, section

SCRIPT = REPO / 'scripts' / 'report_regulations.py'
MESSAGE = 'valid_for_current_date must be a boolean'
TRUTHY = ['false', 'true', 1, ['x'], {'x': 1}]
FALSEY = [None, 0, '', [], {}]


class ValidityTypeTests(unittest.TestCase):
    def test_truthy_non_boolean_validity_is_unreadable(self):
        for status in ('reviewed', 'draft'):
            for value in TRUTHY:
                with self.subTest(status=status, value=value):
                    with self.assertRaises(ValueError) as caught:
                        _region_lines('b', health(rules_review_status=status, valid_for_current_date=value))
                    self.assertEqual(str(caught.exception), MESSAGE)

    def test_falsey_non_boolean_validity_also_refuses(self):
        for value in FALSEY:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                markdown, attention, unreadable = report(make_root(tmp, {'b': health(valid_for_current_date=value)}))
                self.assertEqual(unreadable, ['b'])
                self.assertIn(f'(ValueError: {MESSAGE})', markdown)
                self.assertNotIn(repr(value) + ')', markdown)
        data = {k: v for k, v in health().items() if k != 'valid_for_current_date'}
        with self.assertRaises(KeyError):
            _region_lines('b', data)

    def test_invalid_validity_preserves_healthy_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {'b': health(valid_for_current_date='false'), 'a': health()})
            markdown, attention, unreadable = report(root)
            self.assertEqual(unreadable, ['b'])
            self.assertTrue(attention)
            self.assertEqual(section(markdown, 'a'), A_SECTION)
            self.assertNotIn('Jurisdiction', section(markdown, 'b'))
            summary = Path(tmp) / 'summary.md'
            env = dict(os.environ, GITHUB_STEP_SUMMARY=str(summary))
            done = subprocess.run([sys.executable, '-B', str(SCRIPT), '--root', tmp], capture_output=True, text=True, env=env, cwd=REPO)
            self.assertEqual(done.returncode, 1)
            self.assertNotIn('Traceback', done.stderr)
            self.assertIn('::error::Regulation health unreadable for: b', done.stdout)
            self.assertIn(A_SECTION, summary.read_text())

    def test_boolean_true_false_controls(self):
        clean = dict(review_required=[], areas={'a1': {'name': 'Area 1', 'issues': []}},
                     checks={'s1': {'status': 'match', 'source_status': 'ok'}})
        lines, attention = _region_lines('a', health(**clean))
        self.assertFalse(attention)
        self.assertIn('Species requiring review or a fresh check: none', lines)
        with tempfile.TemporaryDirectory() as tmp:
            markdown, attention, unreadable = report(make_root(tmp, {'a': health(valid_for_current_date=False, **clean)}))
        self.assertTrue(attention)
        self.assertEqual(unreadable, [])
        self.assertIn('Species requiring review or a fresh check: Lingcod', markdown)
        self.assertIn('Area notices requiring a fresh rule check: Area 1', markdown)


if __name__ == '__main__':
    unittest.main()

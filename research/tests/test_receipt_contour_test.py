"""Focused tests for the contour test receipt generator."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from research.scripts import receipt_contour_test as receipt


class ContourReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'research/receipts').mkdir(parents=True)
        for name in receipt.FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'provenance': {'review_expires': '2027-01-01'}}))
        self.count = len(receipt.REQUIRED_CASES)
        self.rows = [f'ok {n} - {name}' for n, name in enumerate(receipt.REQUIRED_CASES, 1)]
        self.footer = (f'1..{self.count}\n# tests {self.count}\n# suites 0\n# pass {self.count}\n'
                       '# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n')
        self.tap = self.transcript(self.rows)

    def transcript(self, rows):
        return '\n'.join(['TAP version 13', '# private TAP body marker', *rows, self.footer])

    def make(self, tap=None, exit_code=0, ran_at='2026-11-02T12:00:00Z'):
        return receipt.create_receipt(self.root, self.tap if tap is None else tap,
                                      'a' * 40, 'v22.0.0', ran_at, exit_code)

    def test_incomplete_runs_and_node_failure_are_not_pass(self):
        short = self.tap.replace(f'# pass {self.count}\n', f'# pass {self.count - 1}\n')
        cases = {
            'all skipped': (self.tap.replace(f'# pass {self.count}', '# pass 0')
                            .replace('# skipped 0', f'# skipped {self.count}'), 0),
            'one skipped': (short.replace('# skipped 0', '# skipped 1'), 0),
            'cancelled': (short.replace('# cancelled 0', '# cancelled 1'), 0),
            'todo': (self.tap.replace('# todo 0', '# todo 1'), 0),
            'pass short of tests': (short, 0),
            'failed': (short.replace('# fail 0', '# fail 1'), 0),
            'changed count': (self.tap.replace(f'# tests {self.count}', f'# tests {self.count - 1}'), 0),
            'node exit 1': (self.tap, 1),
            'node killed': (self.tap, -9),
        }
        for label, (tap, code) in cases.items():
            with self.subTest(label):
                out = self.make(tap, code)
                data = json.loads(out.read_text())
                out.unlink()
                self.assertEqual(data['result'], 'fail')
                self.assertEqual(data['exit_code'], code)

    def test_missing_cancelled_summary_or_bad_exit_code_does_not_write(self):
        with self.assertRaises(ValueError):
            self.make(self.tap.replace('# cancelled 0\n', ''))
        for code in (None, '0', 0.0, True):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.make(exit_code=code)
        self.assertEqual(list((self.root / 'research/receipts').iterdir()), [])

    def test_main_returns_one_and_records_fail_when_node_exits_one(self):
        with mock.patch.object(receipt, 'ROOT', self.root), \
             mock.patch.object(receipt.subprocess, 'check_output', side_effect=['a' * 40, 'v22']), \
             mock.patch.object(receipt.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stdout = self.tap
            self.assertEqual(receipt.main(), 1)
        [out] = (self.root / 'research/receipts').iterdir()
        data = json.loads(out.read_text())
        self.assertEqual((data['result'], data['exit_code']), ('fail', 1))

    def test_main_returns_zero_on_clean_pass(self):
        with mock.patch.object(receipt, 'ROOT', self.root), \
             mock.patch.object(receipt.subprocess, 'check_output', side_effect=['a' * 40, 'v22']), \
             mock.patch.object(receipt.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = self.tap
            self.assertEqual(receipt.main(), 0)
        [out] = (self.root / 'research/receipts').iterdir()
        self.assertEqual(json.loads(out.read_text())['result'], 'pass')

    def test_success_and_receipt_privacy(self):
        out = self.make()
        text = out.read_text()
        data = json.loads(text)
        self.assertEqual(data['result'], 'pass')
        self.assertEqual(data['suite_version'], receipt.SUITE_VERSION)
        self.assertEqual((data['tests'], data['pass'], data['fail'], data['skipped']),
                         (self.count, self.count, 0, 0))
        self.assertEqual(data['review_expires'], '2027-01-01')
        self.assertEqual([item['path'] for item in data['files']], list(receipt.FILES))
        self.assertTrue(all(len(item['sha256']) == 64 for item in data['files']))
        self.assertNotIn(str(self.root), text)
        self.assertNotIn('private TAP body marker', text)

    def test_green_summary_cannot_substitute_for_reviewed_case_results(self):
        # A different test can keep the total green while losing the export guard.
        index = next(i for i, row in enumerate(self.rows) if 'contour_invalid_expiry_never_exports:' in row)
        case = self.rows[index]
        cases = {
            'summary only': self.transcript([]),
            'same count with a replacement': self.tap.replace(case, f'ok {index + 1} - unrelated replacement'),
            'indented result': self.tap.replace(case, '    ' + case),
            'skip directive': self.tap.replace(case, case + ' # SKIP'),
            'failure with a green summary': self.tap.replace(case, 'not ' + case),
            'missing plan': self.tap.replace(f'1..{self.count}\n', ''),
        }
        for label, tap in cases.items():
            with self.subTest(label):
                out = self.make(tap)
                data = json.loads(out.read_text())
                out.unlink()
                self.assertEqual((data['tests'], data['pass']), (self.count, self.count))
                self.assertEqual(data['result'], 'fail')

    def test_missing_and_non_numeric_summaries_do_not_write(self):
        for tap in (self.tap.replace(f'# pass {self.count}\n', ''), self.tap.replace(f'# tests {self.count}', '# tests bad')):
            with self.subTest(tap=tap), self.assertRaises(ValueError):
                self.make(tap)
        self.assertEqual(list((self.root / 'research/receipts').iterdir()), [])

    def test_existing_receipt_is_unchanged(self):
        historical = self.root / 'research/receipts/morro-bay-depth-contours-test-2026-11-02.json'
        historical.write_bytes(b'{"schema_version": 2}\n')
        out = self.make()
        original = out.read_bytes()
        retry = self.make(ran_at='2026-11-02T12:00:00.000001Z')
        self.assertNotEqual(out, retry)
        self.assertEqual(json.loads(retry.read_text())['result'], 'pass')
        with self.assertRaises(FileExistsError):
            self.make()
        self.assertEqual(out.read_bytes(), original)
        self.assertEqual(historical.read_bytes(), b'{"schema_version": 2}\n')

    def test_missing_or_symlinked_contour_does_not_write(self):
        path = self.root / receipt.FILES[0]
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.make()
        path.symlink_to(self.root / receipt.FILES[1])
        with self.assertRaises(ValueError):
            self.make()
        self.assertEqual(list((self.root / 'research/receipts').iterdir()), [])

    def test_main_returns_one_on_invalid_tap(self):
        with mock.patch.object(receipt.subprocess, 'check_output', side_effect=['a' * 40, 'v22']), \
             mock.patch.object(receipt.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'not TAP'
            self.assertEqual(receipt.main(), 1)


if __name__ == '__main__':
    unittest.main()

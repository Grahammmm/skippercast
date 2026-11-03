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
        self.tap = 'TAP version 13\nok 1 - private TAP body marker\n# tests 16\n# pass 16\n# fail 0\n# skipped 0\n'

    def make(self, tap=None):
        return receipt.create_receipt(self.root, self.tap if tap is None else tap,
                                      'a' * 40, 'v22.0.0', '2026-11-02T12:00:00Z')

    def test_success_and_receipt_privacy(self):
        out = self.make()
        text = out.read_text()
        data = json.loads(text)
        self.assertEqual(data['result'], 'pass')
        self.assertEqual((data['tests'], data['pass'], data['fail'], data['skipped']), (16, 16, 0, 0))
        self.assertEqual(data['review_expires'], '2027-01-01')
        self.assertEqual([item['path'] for item in data['files']], list(receipt.FILES))
        self.assertTrue(all(len(item['sha256']) == 64 for item in data['files']))
        self.assertNotIn(str(self.root), text)
        self.assertNotIn('private TAP body marker', text)

    def test_failure_and_changed_count_are_not_pass(self):
        for tap in (self.tap.replace('# fail 0', '# fail 1'),
                    self.tap.replace('# tests 16', '# tests 14')):
            with self.subTest(tap=tap), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / 'research/receipts').mkdir(parents=True)
                for name in receipt.FILES:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('{"provenance":{"review_expires":"2027-01-01"}}')
                out = receipt.create_receipt(root, tap, 'b' * 40, 'v22', '2026-11-02T12:00:00Z')
                data = json.loads(out.read_text())
                self.assertEqual(data['result'], 'fail')
                self.assertEqual(data['fail'], 1 if '# fail 1' in tap else 0)
                self.assertEqual(data['tests'], 14 if '# tests 14' in tap else 16)

    def test_missing_and_non_numeric_summaries_do_not_write(self):
        for tap in (self.tap.replace('# pass 16\n', ''), self.tap.replace('# tests 16', '# tests bad')):
            with self.subTest(tap=tap), self.assertRaises(ValueError):
                self.make(tap)
        self.assertEqual(list((self.root / 'research/receipts').iterdir()), [])

    def test_existing_receipt_is_unchanged(self):
        out = self.make()
        original = out.read_bytes()
        with self.assertRaises(FileExistsError):
            self.make()
        self.assertEqual(out.read_bytes(), original)

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

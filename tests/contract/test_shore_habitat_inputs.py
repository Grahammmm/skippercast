"""collect_shore_habitat refusals (RF2320-1): one named stderr line, exit 1, and no half-written file.

Saved sources are the synthetic fixtures of test_shore_habitat.py; nothing reads the network or var/.
"""
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests._support import ROOT
from tests.contract.test_shore_habitat import importer, synthetic_bodies, write_saved_sources

FETCHED = '2026-10-03T00:00:00.000Z'
PREFIX = 'collect_shore_habitat: '


class SavedSourceRefusals(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.sources = self.dir / 'sources'
        self.sources.mkdir()
        self.output = self.dir / 'out' / 'morro-bay.geojson'
        self.bodies, self.receipts = synthetic_bodies(FETCHED)
        write_saved_sources(self.sources, self.bodies, self.receipts)

    def run_main(self, *extra):
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = importer.main(['--sources', str(self.sources), '--output', str(self.output), *extra])
        return code, err.getvalue(), out.getvalue()

    def assertRefused(self, message, code=1, *extra):
        result, err, out = self.run_main(*extra)
        self.assertEqual((result, err, out), (code, PREFIX + message + '\n', ''))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.leftovers(), [])

    def leftovers(self):
        return sorted(p.name for p in self.dir.rglob('*.tmp'))

    def save_noaa(self, body):
        """A noaa response whose receipt matches, so the refusal comes from the build, not the receipt check."""
        bodies, receipts = dict(self.bodies), dict(self.receipts)
        bodies['noaa'] = body
        receipts['noaa'] = importer.receipt(receipts['noaa']['url'], body, FETCHED)
        write_saved_sources(self.sources, bodies, receipts)

    def test_missing_receipts_exits_1_with_one_line_and_no_traceback(self):
        (self.sources / 'receipts.json').unlink()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/collect_shore_habitat.py'), '--sources', str(self.sources),
                                 '--output', str(self.output)], capture_output=True, text=True, timeout=120)
        self.assertEqual((result.returncode, result.stderr, result.stdout),
                         (1, PREFIX + 'Unreadable saved receipts: receipts.json\n', ''))
        self.assertFalse(self.output.exists())

    def test_unreadable_or_misshaped_receipts_are_named(self):
        cases = [(b'[]', 'Saved receipts must be a JSON object'), (b'"x"', 'Saved receipts must be a JSON object'),
                 (b'{"noaa": ', 'Unreadable saved receipts: receipts.json'),
                 (b'{"noaa": "\xff\xfe\x80"}', 'Unreadable saved receipts: receipts.json'),
                 (b'[' * 100000 + b']' * 100000, 'Unreadable saved receipts: receipts.json')]
        for raw, message in cases:
            with self.subTest(raw=raw[:12]):
                (self.sources / 'receipts.json').write_bytes(raw)
                self.assertRefused(message)
        (self.sources / 'receipts.json').unlink()
        (self.sources / 'receipts.json').mkdir()
        self.assertRefused('Unreadable saved receipts: receipts.json')

    def test_missing_or_unreadable_response_names_its_key(self):
        for key, name in importer.SOURCE_FILES.items():
            with self.subTest(key=key):
                write_saved_sources(self.sources, self.bodies, self.receipts)
                (self.sources / name).unlink()
                self.assertRefused('Missing or invalid saved source receipt: ' + key)
                (self.sources / name).mkdir()
                self.assertRefused('Missing or invalid saved source receipt: ' + key)
                (self.sources / name).rmdir()

    def test_tampered_response_exits_1_with_one_line(self):
        (self.sources / importer.SOURCE_FILES['access']).write_bytes(self.bodies['access'] + b' ')
        self.assertRefused('Missing or invalid saved source receipt: access')

    def test_failing_build_leaves_an_existing_output_byte_identical(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b'{"previous": true}\n')
        failures = [lambda: (self.sources / 'receipts.json').write_text('[]') and None,
                    lambda: self.save_noaa(b'{"type": "FeatureCollection", "features": []}'),
                    lambda: mock.patch.object(importer.validate, 'check', side_effect=importer.validate.ContractError('bad shape'))]
        for n, fail in enumerate(failures):
            with self.subTest(n=n):
                write_saved_sources(self.sources, self.bodies, self.receipts)
                patcher = fail()
                with patcher or contextlib.nullcontext():
                    result, err, _ = self.run_main()
                self.assertEqual((result, err.count('\n'), err.startswith(PREFIX)), (1, 1, True))
                self.assertEqual(self.output.read_bytes(), b'{"previous": true}\n')
                self.assertEqual(self.leftovers(), [])

    def test_missing_dependency_keeps_its_message_and_exit_2(self):
        error = importer.validate.MissingDependency(importer.validate.INSTALL_HINT)
        with mock.patch.object(importer.validate, 'check', side_effect=error):
            self.assertRefused(importer.validate.INSTALL_HINT, 2)

    def test_success_writes_saved_sources_then_the_asset_whole(self):
        written = []
        real = importer._write_atomic
        with mock.patch.dict(os.environ, {'SKIPPERCAST_VALIDATE': 'off'}), \
                mock.patch.object(importer, '_write_atomic', side_effect=lambda p, d: (written.append(p.name), real(p, d))):
            result, err, out = self.run_main('--save-sources', str(self.dir / 'saved'))
        self.assertEqual((result, err), (0, ''))
        self.assertEqual(json.loads(out)['bytes'], self.output.stat().st_size)
        self.assertEqual(written, [*importer.SOURCE_FILES.values(), 'receipts.json', 'morro-bay.geojson'])
        self.assertEqual(importer.load_saved(self.dir / 'saved', 'morro-bay', datetime.now(timezone.utc)), (self.bodies, self.receipts))
        self.assertEqual(self.leftovers(), [])


class WriteAtomic(unittest.TestCase):
    def test_failed_replace_keeps_the_original_and_removes_the_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'asset.geojson'
            target.write_bytes(b'original\n')
            with mock.patch.object(importer.os, 'replace', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    importer._write_atomic(target, b'new\n')
            self.assertEqual(target.read_bytes(), b'original\n')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['asset.geojson'])
            importer._write_atomic(target, b'new\n')
            self.assertEqual(target.read_bytes(), b'new\n')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['asset.geojson'])


if __name__ == '__main__':
    unittest.main()

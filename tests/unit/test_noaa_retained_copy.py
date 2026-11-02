from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase, mock

from scripts import audit_noaa_survey_products as products
from scripts import discover_noaa_surveys as discovery
from tests._support import NOW


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class RetainedCopyTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'dist/data').mkdir(parents=True)
        (self.root / 'dist/data/coastal-sectors.json').write_text(json.dumps({'sectors': [{'id': 'a', 'bounds': [0, 0, 1, 1]}]}))
        self.discovery = self.root / 'discovery.json'
        self.discovery.write_text(json.dumps({'scope': 'noaa-bag-survey-discovery',
                                              'sectors': [{'surveys': [{'id': 'H1', 'catalog_url': 'https://x'}]}]}))
        self.output = self.root / 'out/result.json'
        self.previous = self.root / 'previous.json'
        self.calls = []

    def fake_scan(self, sectors, previous=None, *, now=None):
        self.calls.append(previous)
        return {'health': {'status': 'ok'}, 'distinct_survey_leads': 0, 'sectors': []}

    def fake_audit(self, discovery_doc, previous=None, *, now=None):
        self.calls.append(previous)
        return {'health': {'status': 'ok'}, 'bag_link_count': 0, 'report_link_count': 0, 'survey_count': 1}

    def doc(self, when=None):
        stamp = (when or NOW - timedelta(days=2)).isoformat()
        return {'health': {'status': 'ok'}, 'last_complete_scan_at': stamp,
                'sectors': [{'sector_id': 'a', 'surveys': []}], 'surveys': [{'id': 'H1', 'status': 'ok'}]}

    def run_main(self, module, output=None, *patches):
        output = output or self.output
        stderr = io.StringIO()
        if module is discovery:
            argv = ['--output', str(output), '--previous', str(self.previous)]
            base = [mock.patch.object(discovery, 'ROOT', self.root), mock.patch.object(discovery, 'scan', self.fake_scan)]
        else:
            argv = ['--discovery', str(self.discovery), '--output', str(output), '--previous', str(self.previous)]
            base = [mock.patch.object(products, 'audit', self.fake_audit)]
        with ExitStack() as stack, redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            for patch in [mock.patch.object(module, 'datetime', FixedDatetime), *base, *patches]:
                stack.enter_context(patch)
            module.main(argv)
        return stderr.getvalue()

    def test_retained_copy_is_the_validated_bytes_not_a_second_read(self):
        for module in (discovery, products):
            with self.subTest(module.__name__):
                raw = json.dumps(self.doc(), indent=2).encode()
                self.previous.write_bytes(raw)
                real = module._previous_bytes

                def swapped(path):  # the file changes on disk right after it was validated
                    result = real(path)
                    path.write_bytes(b'{"swapped": true}\n')
                    return result

                with mock.patch.object(module, '_previous_bytes', swapped):
                    self.assertEqual(self.run_main(module), '')
                self.assertEqual(self.output.read_bytes(), raw)
                self.assertEqual(self.previous.read_bytes(), b'{"swapped": true}\n')
                self.assertFalse(self.output.with_suffix('.json.tmp').exists())
                self.assertEqual(self.calls, [])

    def test_output_equal_to_previous_is_unchanged_and_leaves_no_tmp(self):
        for module in (discovery, products):
            with self.subTest(module.__name__):
                raw = json.dumps(self.doc(), indent=1).encode()
                self.previous.write_bytes(raw)
                self.assertEqual(self.run_main(module, self.previous), '')
                self.assertEqual(self.previous.read_bytes(), raw)
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['discovery.json', 'dist', 'previous.json'])
                self.assertEqual(self.calls, [])

    def test_failed_tmp_write_leaves_existing_output_unchanged(self):
        for module in (discovery, products):
            with self.subTest(module.__name__):
                self.previous.write_text(json.dumps(self.doc()))
                self.output.parent.mkdir(parents=True, exist_ok=True)
                self.output.write_bytes(b'OLD OUTPUT\n')
                with self.assertRaises(OSError):
                    self.run_main(module, None, mock.patch.object(Path, 'write_bytes', side_effect=OSError(28, 'No space left')))
                self.assertEqual(self.output.read_bytes(), b'OLD OUTPUT\n')
                self.assertEqual(self.calls, [])

    def test_audit_future_scan_time_is_named_and_reaudited(self):
        for hours in (1, 24 * 400):
            with self.subTest(hours=hours):
                self.calls.clear()
                document = self.doc(NOW + timedelta(hours=hours))
                self.previous.write_text(json.dumps(document))
                stderr = self.run_main(products)
                self.assertEqual(stderr, 'previous inventory ignored: scan time is in the future\n')
                self.assertEqual(self.calls, [document])
                self.assertEqual(json.loads(self.output.read_text())['survey_count'], 1)

    def test_audit_scan_time_equal_to_now_is_not_future(self):
        self.previous.write_bytes(raw := json.dumps(self.doc(NOW)).encode())
        self.assertEqual(self.run_main(products), '')
        self.assertEqual((self.output.read_bytes(), self.calls), (raw, []))

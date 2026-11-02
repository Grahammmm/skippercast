from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase, mock

from scripts import discover_noaa_surveys as discovery
from tests._support import NOW


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class PreviousScanTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'dist/data').mkdir(parents=True)
        (self.root / 'dist/data/coastal-sectors.json').write_text(json.dumps({'sectors': [{'id': 'a', 'bounds': [0, 0, 1, 1]}]}))
        self.output = self.root / 'out/survey-discovery.json'
        self.previous = self.root / 'previous.json'
        self.calls = []

    def fake_scan(self, sectors, previous=None, *, now=None):
        self.calls.append(previous)
        return {'health': {'status': 'ok'}, 'distinct_survey_leads': 0, 'sectors': []}

    def run_main(self, *extra):
        stderr = io.StringIO()
        with mock.patch.object(discovery, 'ROOT', self.root), mock.patch.object(discovery, 'scan', self.fake_scan), \
                mock.patch.object(discovery, 'datetime', FixedDatetime), redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            discovery.main(['--output', str(self.output), *extra])
        return stderr.getvalue()

    def doc(self, age_days=2, **fields):
        stamp = (NOW - timedelta(days=age_days)).isoformat()
        return {'health': {'status': 'ok'}, 'last_complete_scan_at': stamp, 'sectors': [{'sector_id': 'a', 'surveys': []}], **fields}

    def test_max_age_days_outside_1_to_365_is_usage_before_any_scan(self):
        self.previous.write_text(json.dumps(self.doc()))
        for value in ('0', '-1', '366', '1000000000', 'abc', '1.5', ''):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit) as caught:
                    self.run_main('--previous', str(self.previous), '--max-age-days', value)
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(self.calls, [])
                self.assertFalse(self.output.exists())

    def test_unreadable_previous_is_ignored_with_one_line_and_full_scan(self):
        secret = b'SECRET-CONTENT'
        for raw in (b'{not json ' + secret, json.dumps([self.doc()]).encode(), b'\xff\xfe' + secret, b'"text"'):
            with self.subTest(raw=raw[:12]):
                self.calls.clear()
                self.output.unlink(missing_ok=True)
                self.previous.write_bytes(raw)
                stderr = self.run_main('--previous', str(self.previous))
                self.assertEqual(stderr, 'previous scan ignored: unreadable\n')
                self.assertEqual(self.calls, [None])
                self.assertTrue(self.output.exists())

    def test_unusable_scan_time_rescans_and_keeps_rows_for_scan(self):
        future = (NOW + timedelta(days=1)).isoformat()
        cases = [({'last_complete_scan_at': '2026-10-30T12:00:00'}, 'scan time has no UTC offset'),
                 ({'last_complete_scan_at': 'yesterday'}, 'bad scan time'),
                 ({'last_complete_scan_at': 20261030}, 'bad scan time'),
                 ({'last_complete_scan_at': None}, 'no scan time'),
                 ({'last_complete_scan_at': future}, 'scan time is in the future')]
        for fields, reason in cases:
            with self.subTest(reason=reason, fields=fields):
                self.calls.clear()
                document = self.doc(**fields)
                self.previous.write_text(json.dumps(document))
                stderr = self.run_main('--previous', str(self.previous))
                self.assertEqual(stderr, f'previous scan ignored: {reason}\n')
                self.assertEqual(self.calls, [document])
        missing = self.doc()
        del missing['last_complete_scan_at']
        missing['sectors'] = 'not-a-list'
        self.calls.clear()
        self.previous.write_text(json.dumps(missing))
        self.assertEqual(self.run_main('--previous', str(self.previous)), 'previous scan ignored: no scan time\n')
        self.assertEqual(self.calls, [None])

    def test_fresh_complete_previous_is_retained_byte_for_byte(self):
        raw = json.dumps(self.doc(age_days=2), indent=1).encode()
        for days in ('30', '365'):
            with self.subTest(days=days):
                self.previous.write_bytes(raw)
                self.assertEqual(self.run_main('--previous', str(self.previous), '--max-age-days', days), '')
                self.assertEqual(self.output.read_bytes(), raw)
                self.assertEqual(self.calls, [])

    def test_stale_previous_rescans_silently(self):
        for age, days in ((31, '30'), (2, '1')):
            with self.subTest(age=age, days=days):
                self.calls.clear()
                document = self.doc(age_days=age)
                self.previous.write_text(json.dumps(document))
                self.assertEqual(self.run_main('--previous', str(self.previous), '--max-age-days', days), '')
                self.assertEqual(self.calls, [document])

    def test_missing_previous_path_is_a_silent_full_scan(self):
        self.assertEqual(self.run_main('--previous', str(self.root / 'absent.json')), '')
        self.assertEqual(self.calls, [None])
        self.assertEqual(json.loads(self.output.read_text())['health']['status'], 'ok')

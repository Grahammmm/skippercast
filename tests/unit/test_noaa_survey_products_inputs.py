from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

from scripts import audit_noaa_survey_products as products
from tests._support import NOW, ROOT

SCOPE = 'noaa-bag-survey-discovery'


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class AuditInputTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.discovery = self.root / 'discovery.json'
        self.discovery.write_text(json.dumps(self.lead_doc('H1', 'H2')))
        self.output = self.root / 'out/products.json'
        self.previous = self.root / 'previous.json'
        self.calls = []

    @staticmethod
    def lead_doc(*ids):
        return {'scope': SCOPE, 'sectors': [{'surveys': [{'id': ident, 'catalog_url': 'https://x'} for ident in ids]}]}

    def fake_audit(self, discovery, previous=None, *, now=None):
        self.calls.append(previous)
        return {'health': {'status': 'ok'}, 'bag_link_count': 1, 'report_link_count': 2, 'survey_count': 3}

    def run_main(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(products, 'audit', self.fake_audit), mock.patch.object(products, 'datetime', FixedDatetime), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = products.main(['--discovery', str(self.discovery), '--output', str(self.output), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def inventory(self, age_days=3, ids=('H1', 'H2'), **fields):
        stamp = (NOW - timedelta(days=age_days)).isoformat()
        return {'health': {'status': 'ok'}, 'last_complete_scan_at': stamp,
                'surveys': [{'id': ident, 'status': 'ok'} for ident in ids], **fields}

    def test_bad_discovery_is_refused_with_one_named_reason_and_no_output(self):
        cases = [(b'{not json SECRET', 'discovery file is unreadable'),
                 (b'\xff\xfeSECRET', 'discovery file is unreadable'),
                 (json.dumps([self.lead_doc('H1')]).encode(), 'discovery file is not a NOAA survey discovery object'),
                 (json.dumps({'scope': 'SECRET', 'sectors': [{'surveys': []}]}).encode(), 'discovery file is not a NOAA survey discovery object'),
                 (json.dumps({'scope': SCOPE, 'sectors': []}).encode(), 'discovery file has no sector list'),
                 (json.dumps({'scope': SCOPE, 'sectors': {'a': 1}}).encode(), 'discovery file has no sector list'),
                 (json.dumps({'scope': SCOPE, 'sectors': [{'surveys': []}, {'id': 'SECRET'}]}).encode(), 'sector 1 has no survey list'),
                 (json.dumps({'scope': SCOPE, 'sectors': ['SECRET']}).encode(), 'sector 0 has no survey list'),
                 (json.dumps({'scope': SCOPE, 'sectors': [{'surveys': [{'id': 'H1'}, {}]}]}).encode(), 'sector 0 lead 1 has no string id'),
                 (json.dumps({'scope': SCOPE, 'sectors': [{'surveys': [{'id': 7}]}]}).encode(), 'sector 0 lead 0 has no string id')]
        self.previous.write_text(json.dumps(self.inventory()))
        for raw, reason in cases:
            with self.subTest(reason=reason, raw=raw[:30]):
                self.discovery.write_bytes(raw)
                code, stdout, stderr = self.run_main('--previous', str(self.previous))
                self.assertEqual((code, stdout, stderr), (1, '', f'audit refused: {reason}\n'))
                self.assertEqual(self.calls, [])
                self.assertFalse(self.output.exists())

    def test_missing_discovery_file_is_refused(self):
        self.discovery.unlink()
        self.assertEqual(self.run_main(), (1, '', 'audit refused: discovery file is unreadable\n'))

    def test_bad_discovery_exit_code_reaches_the_shell(self):
        self.discovery.write_text('[]')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/audit_noaa_survey_products.py'), '--discovery',
                                 str(self.discovery), '--output', str(self.output)], capture_output=True, text=True, timeout=60)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, '', 'audit refused: discovery file is not a NOAA survey discovery object\n'))
        self.assertFalse(self.output.exists())

    def test_max_age_days_outside_1_to_365_is_usage_error_before_any_read(self):
        self.previous.write_text(json.dumps(self.inventory()))
        for value in ('0', '-3', '366', str(10 ** 9), 'abc', '1.5', ''):
            with self.subTest(value=value), mock.patch.object(Path, 'read_text') as load:
                with self.assertRaises(SystemExit) as caught:
                    self.run_main('--previous', str(self.previous), '--max-age-days', value)
                self.assertEqual(caught.exception.code, 2)
                load.assert_not_called()
                self.assertEqual(self.calls, [])
                self.assertFalse(self.output.exists())

    def test_unusable_previous_is_ignored_with_one_line_and_full_audit(self):
        no_time = self.inventory()
        del no_time['last_complete_scan_at']
        no_list = self.inventory()
        del no_list['surveys']
        cases = [(b'{not json SECRET', 'unreadable'), (b'\xff\xfeSECRET', 'unreadable'),
                 (json.dumps([self.inventory()]).encode(), 'unreadable'),
                 (json.dumps(self.inventory(last_complete_scan_at='2026-09-25T12:00:00')).encode(), 'scan time has no UTC offset'),
                 (json.dumps(self.inventory(last_complete_scan_at='yesterday')).encode(), 'bad scan time'),
                 (json.dumps(self.inventory(last_complete_scan_at=20260925)).encode(), 'bad scan time'),
                 (json.dumps(no_time).encode(), 'no scan time'),
                 (json.dumps(self.inventory(last_complete_scan_at=None)).encode(), 'no scan time'),
                 (json.dumps(no_list).encode(), 'no survey list'),
                 (json.dumps(self.inventory(surveys=[{'id': 5}])).encode(), 'no survey list'),
                 (json.dumps(self.inventory(surveys=['H1'])).encode(), 'no survey list')]
        for raw, reason in cases:
            with self.subTest(reason=reason, raw=raw[:30]):
                self.calls.clear()
                self.output.unlink(missing_ok=True)
                self.previous.write_bytes(raw)
                code, stdout, stderr = self.run_main('--previous', str(self.previous))
                self.assertEqual((code, stderr), (None, f'previous inventory ignored: {reason}\n'))
                self.assertEqual(stdout, 'ok: 1 BAG links, 2 report links among 3 surveys\n')
                self.assertEqual(self.calls, [None])
                self.assertTrue(self.output.exists())

    def test_previous_that_cannot_be_stat_or_opened_is_ignored_not_a_crash(self):
        locked = self.root / 'locked'
        locked.mkdir()
        (locked / 'previous.json').write_text(json.dumps(self.inventory()))
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o700)
        self.previous.write_text(json.dumps(self.inventory()))
        real_read = Path.read_bytes

        def denied(path, *args, **kwargs):  # the stat/open of --previous fails as it does under a 0700 parent
            if path == self.previous:
                raise PermissionError(13, 'Permission denied', str(path))
            return real_read(path, *args, **kwargs)

        cases = {'directory': (self.root, nullcontext()),
                 'open error': (self.previous, mock.patch.object(Path, 'read_bytes', denied)),
                 'inaccessible parent': (locked / 'previous.json', nullcontext())}
        for name, (path, patch) in cases.items():
            with self.subTest(name):
                if name == 'inaccessible parent' and os.access(locked, os.X_OK):
                    self.skipTest('running as a user that bypasses directory permissions')
                self.calls.clear()
                self.output.unlink(missing_ok=True)
                with patch:
                    code, stdout, stderr = self.run_main('--previous', str(path))
                self.assertEqual((code, stderr), (None, 'previous inventory ignored: unreadable\n'))
                self.assertEqual(stdout, 'ok: 1 BAG links, 2 report links among 3 surveys\n')
                self.assertEqual(self.calls, [None])
                self.assertTrue(self.output.exists())

    def test_fresh_complete_previous_with_same_ids_is_retained_byte_for_byte(self):
        raw = json.dumps(self.inventory(), indent=1).encode()
        for days in ('30', '4', '365'):
            with self.subTest(days=days):
                self.previous.write_bytes(raw)
                code, stdout, stderr = self.run_main('--previous', str(self.previous), '--max-age-days', days)
                self.assertEqual((code, stderr), (None, ''))
                self.assertTrue(stdout.startswith('Retained complete NOAA product inventory from 2026-09-25T12:00:00+00:00'))
                self.assertEqual(self.output.read_bytes(), raw)
                self.assertEqual(self.calls, [])

    def test_usable_previous_that_cannot_be_reused_is_passed_to_a_silent_reaudit(self):
        cases = {'different ids': (self.inventory(ids=('H1', 'H3')), '30'), 'stale': (self.inventory(), '3'),
                 'future': (self.inventory(age_days=-1), '30'), 'degraded': (self.inventory(health={'status': 'degraded'}), '30'),
                 'odd health': (self.inventory(health='ok'), '30')}
        for name, (document, days) in cases.items():
            with self.subTest(name):
                self.calls.clear()
                self.previous.write_text(json.dumps(document))
                code, stdout, stderr = self.run_main('--previous', str(self.previous), '--max-age-days', days)
                self.assertEqual((code, stderr), (None, 'previous inventory ignored: scan time is in the future\n' if name == 'future' else ''))
                self.assertEqual(self.calls, [document])
                self.assertEqual(json.loads(self.output.read_text())['health']['status'], 'ok')

    def test_valid_discovery_without_previous_audits_once(self):
        for extra in ((), ('--previous', str(self.root / 'absent.json'))):
            with self.subTest(extra=extra):
                self.calls.clear()
                self.assertEqual(self.run_main(*extra), (None, 'ok: 1 BAG links, 2 report links among 3 surveys\n', ''))
                self.assertEqual(self.calls, [None])
                self.assertEqual(json.loads(self.output.read_text())['survey_count'], 3)

"""--previous handling of the USGS map pair: unusable is ignored, max age 1..365, atomic retained copy."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from research.lib.paths import ROOT
from research.scripts import audit_usgs_map_metadata as audit_mod

SPEC = importlib.util.spec_from_file_location('map_blocks_previous', ROOT / 'research/scripts' / 'discover_usgs_map_blocks.py')
blocks_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(blocks_mod)

CATALOG = 'https://pubs.usgs.gov/ds/781/OffshoreX/data_catalog_OffshoreX.html'
XML_URL = 'https://pubs.usgs.gov/ds/781/OffshoreX/metadata/Bathymetry_X.xml'
PAGES = {blocks_mod.INDEX: b'<a href="OffshoreX/data_catalog_OffshoreX.html">X</a>', CATALOG: b'<table></table>',
         XML_URL: b'<metadata><bounding><westbc>-122.5</westbc><eastbc>-122.4</eastbc>'
                  b'<southbc>37.2</southbc><northbc>37.4</northbc></bounding></metadata>'}
INVENTORY = {'scope': 'usgs-state-waters-map-block-links', 'block_count': 1,
             'blocks': [{'id': 'OffshoreX', 'products': {'bathymetry': [{'metadata_url': XML_URL}]}}]}
# list key -> (module, entry point that takes previous last, row key, leaf URL the fake fetcher can fail)
SCRIPTS = {'blocks': (blocks_mod, 'discover', 'catalog_url', CATALOG),
           'records': (audit_mod, 'audit', 'metadata_url', XML_URL)}


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def fresh(kind, **changes):
    row = {'id': 'OffshoreX', 'catalog_url': CATALOG, 'products': {}} if kind == 'blocks' else \
        {'block_id': 'OffshoreX', 'kind': 'bathymetry', 'metadata_url': XML_URL}
    data = {'schema_version': 1, 'health': {'status': 'ok', 'issues': []}, 'last_complete_scan_at': ago(hours=1), kind: [row]}
    data.update(changes)
    return {key: value for key, value in data.items() if value is not ...}


class PreviousScanTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        (self.tmp / 'inventory.json').write_text(json.dumps(INVENTORY))

    def run_main(self, kind, previous=None, *extra, fail=False):
        mod, entry, _, leaf = SCRIPTS[kind]
        path, out = self.tmp / f'previous-{kind}.json', self.tmp / f'out-{kind}.json'
        out.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        if previous is not None:
            path.write_bytes(previous if isinstance(previous, bytes) else json.dumps(previous, indent=2).encode())
        real, calls, fetched = getattr(mod, entry), [], []

        def fetcher(url):
            fetched.append(url)
            if fail and url == leaf:
                raise OSError('offline')
            return PAGES[url]

        def fake(*args, **kwargs):
            calls.append(args[-1])
            return real(*args, fetcher=fetcher, **kwargs)
        argv = ['script', '--output', str(out), '--previous', str(path), *extra]
        argv += ['--blocks', str(self.tmp / 'inventory.json')] if kind == 'records' else []
        err, code = io.StringIO(), 0
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(mod, entry, fake), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            try:
                mod.main()
            except SystemExit as stop:
                code = stop.code
        return code, err.getvalue(), calls, fetched, out

    def assert_rescanned(self, result, reason, passed):
        code, err, calls, fetched, out = result
        self.assertEqual(code, 0)
        self.assertEqual(err.strip(), f'previous scan ignored: {reason}' if reason else '')
        self.assertEqual(calls, [passed])
        self.assertTrue(fetched)
        self.assertIn('collected_at', json.loads(out.read_text()))

    def test_unreadable_previous_is_ignored_with_one_line(self):
        for kind in SCRIPTS:
            for raw in (b'{"health": {"status": "ok"', b'\xff\xfe{}', b'[]', b'"x"'):
                with self.subTest(kind=kind, raw=raw):
                    self.assert_rescanned(self.run_main(kind, raw), 'unreadable', None)
            with self.subTest(kind=kind, raw='absent'):
                self.assert_rescanned(self.run_main(kind), None, None)

    def test_bad_scan_time_is_named_and_rescanned_without_previous(self):
        cases = [('2026-10-01T00:00:00', 'scan time has no UTC offset'), ('soon', 'bad scan time'), (5, 'bad scan time'),
                 (..., 'no scan time'), (None, 'no scan time'), (ago(days=-1), 'scan time is in the future')]
        for kind in SCRIPTS:
            for when, reason in cases:
                with self.subTest(kind=kind, when=when):
                    # the leaf fetch fails, so any row or scan time that survives could only come from the previous
                    result = self.run_main(kind, fresh(kind, last_complete_scan_at=when), fail=True)
                    self.assert_rescanned(result, reason, None)
                    data = json.loads(result[4].read_text())
                    self.assertEqual([row['status'] for row in data[kind]], ['failed'])
                    self.assertIsNone(data['last_complete_scan_at'])

    def test_stale_degraded_or_misshaped_health_rescans_quietly(self):
        for kind in SCRIPTS:
            for previous in (fresh(kind, last_complete_scan_at=ago(days=2)), fresh(kind, health={'status': 'degraded'}),
                             fresh(kind, health='ok')):
                with self.subTest(kind=kind, previous=previous):
                    self.assert_rescanned(self.run_main(kind, previous, '--max-age-days', '1'), None, previous)

    def test_unusable_list_is_ignored_and_never_retained(self):
        for kind, (_, _, key, _) in SCRIPTS.items():
            for rows in (1, {}, [{key: 5}], [1], ...):
                with self.subTest(kind=kind, rows=rows):
                    result = self.run_main(kind, fresh(kind, **{kind: rows}), fail=True)
                    self.assert_rescanned(result, f'{kind} not a usable list', None)
                    self.assertEqual([row['status'] for row in json.loads(result[4].read_text())[kind]], ['failed'])

    def test_max_age_days_bounded(self):
        for kind in SCRIPTS:
            for value in ('0', '-1', '366', 'x', '1.5', ''):
                with self.subTest(kind=kind, value=value):
                    code, err, calls, fetched, out = self.run_main(kind, fresh(kind), '--max-age-days', value)
                    self.assertEqual(code, 2)
                    self.assertIn('--max-age-days', err)
                    self.assertEqual((calls, fetched, out.exists()), ([], [], False))
            for value in ('1', '365', ' 30 '):
                with self.subTest(kind=kind, value=value):
                    code, _, calls, _, out = self.run_main(kind, fresh(kind), '--max-age-days', value)
                    self.assertEqual((code, calls, out.exists()), (0, [], True))

    def test_fresh_complete_previous_retained_byte_identical(self):
        for kind in SCRIPTS:
            with self.subTest(kind=kind):
                previous = fresh(kind)
                code, err, calls, fetched, out = self.run_main(kind, previous)
                self.assertEqual((code, err, calls, fetched), (0, '', [], []))
                self.assertEqual(out.read_bytes(), json.dumps(previous, indent=2).encode())
                self.assertEqual(sorted(path.name for path in self.tmp.glob('*.tmp')), [])

    def test_family_error_only_for_usable_previous(self):
        with self.assertRaisesRegex(ValueError, 'catalog family differs'):
            self.run_main('blocks', fresh('blocks', catalog_family='csmp'))
        for previous in (fresh('blocks', catalog_family='csmp', blocks=1), b'["csmp"]'):
            with self.subTest(previous=previous):
                result = self.run_main('blocks', previous)
                self.assertEqual(result[0], 0)
                self.assertIn('previous scan ignored:', result[1])
                self.assertEqual(result[2], [None])


if __name__ == '__main__':
    unittest.main()

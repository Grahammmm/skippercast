import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from research.lib.paths import ROOT


SPEC = importlib.util.spec_from_file_location('bag_triage_previous', ROOT / 'research/scripts' / 'triage_noaa_bag_files.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

URL = 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/D00001-D02000/D00182/BAG/D00182_MB_1m_MLLW_1of1.bag'
DISCOVERY = {'scope': 'noaa-bag-survey-discovery', 'sector_count': 1, 'sectors': [{'sector_id': 'sector', 'surveys': [{'id': 'D00182'}]}]}
PRODUCTS = {'scope': 'noaa-survey-product-links', 'survey_count': 1, 'surveys': [{'id': 'D00182', 'products': {'bag': [URL], 'report': ['report']}}]}


def _iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat()


def _inventory(**changes):
    value = {'scope': 'noaa-bag-head-inventory', 'last_complete_scan_at': _iso(-timedelta(hours=1)),
             'health': {'status': 'ok', 'issues': []}, 'files': [{'survey_id': 'D00182', 'url': URL, 'status': 'ok'}]}
    value.update(changes)
    return json.dumps(value).encode()


class PreviousInventoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / 'discovery.json').write_text(json.dumps(DISCOVERY))
        (self.dir / 'products.json').write_text(json.dumps(PRODUCTS))
        self.previous = self.dir / 'previous.json'
        self.output = self.dir / 'out' / 'inventory.json'

    def run_main(self, previous_bytes, *extra):
        if previous_bytes is not None:
            self.previous.write_bytes(previous_bytes)
        calls, err, out = [], io.StringIO(), io.StringIO()
        self.err = err
        def fetcher(url):
            calls.append(url)
            return 500000, 'Tue, 01 Jan 2019 00:00:00 GMT'
        argv = ['--discovery', str(self.dir / 'discovery.json'), '--products', str(self.dir / 'products.json'),
                '--output', str(self.output), '--previous', str(self.previous), *extra]
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            mod.main(argv, fetcher=fetcher)
        return calls, err.getvalue(), out.getvalue()

    def assert_rescan(self, previous_bytes, reason):
        calls, err, out = self.run_main(previous_bytes)
        self.assertEqual(err, f'previous scan ignored: {reason}\n')
        self.assertEqual(calls, [URL])
        self.assertTrue(out.startswith('ok: 1/1 BAG links accessible'), out)
        result = json.loads(self.output.read_text())
        self.assertEqual(result['scope'], 'noaa-bag-head-inventory')
        self.assertEqual([row['status'] for row in result['files']], ['ok'])
        self.assertFalse(self.output.with_suffix('.json.tmp').exists())

    def test_unreadable_previous_is_ignored_and_rescanned(self):
        for raw in (b'{"files": [', b'\xff\xfe{}', b'[]', b'"x"'):
            with self.subTest(raw=raw):
                self.assert_rescan(raw, 'unreadable')

    def test_bad_scan_time_is_ignored_and_rescanned(self):
        cases = [('2026-10-01T00:00:00', 'scan time has no UTC offset'), ('garbage', 'bad scan time'),
                 (5, 'bad scan time'), (None, 'no scan time'),
                 (_iso(timedelta(hours=1)), 'scan time is in the future')]
        for value, reason in cases:
            with self.subTest(value=value):
                self.assert_rescan(_inventory(last_complete_scan_at=value), reason)
        self.assert_rescan(json.dumps({'health': {'status': 'ok'}, 'files': []}).encode(), 'no scan time')

    def test_files_not_a_url_list_is_ignored_and_rescanned(self):
        for files in (1, {}, [1], [{}], [{'url': 5}], [{'url': URL}, 'x']):
            with self.subTest(files=files):
                self.assert_rescan(_inventory(files=files), 'files not a url list')

    def test_max_age_days_bounds(self):
        for value in ('0', '-1', '366', 'abc', '1.5', ''):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit) as raised:
                    self.run_main(_inventory(), '--max-age-days', value)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn('from 1 to 365', self.err.getvalue())
            self.assertFalse(self.output.exists())
        for value in ('1', '365'):
            with self.subTest(value=value):
                calls, err, out = self.run_main(_inventory(), '--max-age-days', value)
                self.assertEqual((calls, err), ([], ''))
                self.assertTrue(out.startswith('Retained complete BAG HEAD inventory from '), out)

    def test_stale_or_mismatched_previous_rescans_without_reason(self):
        calls, err, _ = self.run_main(_inventory(last_complete_scan_at=_iso(-timedelta(days=2))), '--max-age-days', '1')
        self.assertEqual((calls, err), ([URL], ''))
        calls, err, _ = self.run_main(_inventory(files=[{'url': URL + '.other.bag'}]))
        self.assertEqual((calls, err), ([URL], ''))

    def test_fresh_previous_is_retained_atomically_with_identical_bytes(self):
        raw = _inventory()
        self.output.parent.mkdir()
        self.output.write_bytes(b'old output')
        calls, err, out = self.run_main(raw)
        self.assertEqual((calls, err), ([], ''))
        self.assertTrue(out.startswith('Retained complete BAG HEAD inventory from '), out)
        self.assertEqual(self.output.read_bytes(), raw)
        self.assertEqual(sorted(p.name for p in self.output.parent.iterdir()), ['inventory.json'])

    def test_missing_previous_scans_without_reason(self):
        calls, err, _ = self.run_main(None)
        self.assertEqual((calls, err), ([URL], ''))


if __name__ == '__main__':
    unittest.main()

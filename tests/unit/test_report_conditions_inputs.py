"""RF0310-11: a damaged product file is a named failure; the other products are still summarized."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import report_conditions
from scripts.report_conditions import summarize

LATEST = {'completed_at': '2026-11-02T04:00Z', 'health': {'issues': ['buoy-spectrum']},
          'sources': {'b1': {'name': 'Buoy 46011', 'status': 'ok', 'data': {'sample_at': '03:50Z'}},
                      'b2': {'name': 'Buoy 46028', 'status': 'missing', 'data': None}}}
INDEX = {'regions': [
    {'region_id': 'morro-bay', 'status': 'ok', 'issues': [], 'coverage_gaps': ['day-7'],
     'forecast_coverage': {'rated_point_days': 6, 'point_days': 7, 'two_model_point_days': 5}},
    {'region_id': 'crescent-city', 'status': 'failed', 'error_class': 'ValueError', 'error': 'bad',
     'issues': ['refresh-failed']}]}
HEALTH = {'regions': [{'region_id': 'morro-bay', 'status': 'degraded', 'issues': ['sst-analysis']}]}
PRODUCTS = {'latest.json': LATEST, 'regions/index.json': INDEX, 'intelligence-health.json': HEALTH,
            'habitat-health.json': HEALTH}

# Expected output, copied from the pre-change summarize() on the healthy products above.
HEAD = ['## Regional evidence publication', 'Publication: success']
LATEST_LINES = ['Buoy feed collected 2026-11-02T04:00Z', '- Buoy 46011: ok; observed 03:50Z',
                '- Buoy 46028: missing; observed unavailable']
INDEX_LINES = ['\n### regions/index.json', '- morro-bay: ok',
               '  - Seven-day wind + seas: 6/7 point-days; two-model comparison: 5/7', '  - Coverage gap: day-7',
               '- crescent-city: failed', '  - Refresh failed (ValueError): bad; its last publication stays in place',
               '  - Source issue: refresh-failed']
INTEL_LINES = ['\n### intelligence-health.json', '- morro-bay: degraded', '  - Source issue: sst-analysis']
HABITAT_LINES = ['\n### habitat-health.json', '- morro-bay: degraded', '  - Source issue: sst-analysis']


def tail(count):
    return [f'\n{count} source(s) degraded this cycle; the feed was still published with their last good values or gaps.']


def write(root, damaged=None):
    """Write the four healthy products, replacing any named in `damaged` with its raw bytes or object."""
    (root / 'regions').mkdir()
    for name, data in PRODUCTS.items():
        raw = (damaged or {}).get(name, data)
        (root / name).write_bytes(raw if isinstance(raw, bytes) else json.dumps(raw).encode())
    return root


class ReportInputsTests(unittest.TestCase):
    def run_summary(self, damaged=None):
        with tempfile.TemporaryDirectory() as directory:
            return summarize(write(Path(directory), damaged), 'success')

    def test_healthy_products_match_the_pre_change_output(self):
        lines, failures, warnings = self.run_summary()
        self.assertEqual(lines, HEAD + LATEST_LINES + INDEX_LINES + INTEL_LINES + HABITAT_LINES + tail(4))
        self.assertEqual(failures, [])
        self.assertEqual(warnings, ['buoy-spectrum', 'refresh-failed', 'sst-analysis'])

    def test_truncated_latest_is_unreadable_and_regions_are_still_summarized(self):
        lines, failures, warnings = self.run_summary({'latest.json': json.dumps(LATEST)[:40].encode()})
        self.assertEqual(failures, ['latest.json is unreadable'])
        self.assertEqual(lines, HEAD + INDEX_LINES + INTEL_LINES + HABITAT_LINES + tail(3))
        self.assertEqual(warnings, ['refresh-failed', 'sst-analysis'])

    def test_region_row_missing_issues_names_the_key_path(self):
        rows = [INDEX['regions'][0], {k: v for k, v in INDEX['regions'][1].items() if k != 'issues'}]
        lines, failures, _ = self.run_summary({'regions/index.json': {'regions': rows}})
        self.assertEqual(failures, ['regions/index.json: regions[1].issues missing or wrong type'])
        self.assertEqual(lines, HEAD + LATEST_LINES + INTEL_LINES + HABITAT_LINES + tail(3))

    def test_top_level_list_is_a_missing_regions_key(self):
        lines, failures, _ = self.run_summary({'habitat-health.json': [HEALTH]})
        self.assertEqual(failures, ['habitat-health.json: regions missing or wrong type'])
        self.assertEqual(lines, HEAD + LATEST_LINES + INDEX_LINES + INTEL_LINES + tail(3))

    def test_each_first_bad_key_is_named(self):
        cases = {
            'completed_at': {**LATEST, 'completed_at': 7}, 'sources': {**LATEST, 'sources': []},
            'health': {**LATEST, 'health': None}, 'health.issues': {**LATEST, 'health': {}},
            'sources[1].name': {**LATEST, 'sources': {**LATEST['sources'], 'b2': {'status': 'ok'}}},
            'sources[0].name': {**LATEST, 'sources': {'b1': 'Buoy'}}}
        for key, data in cases.items():
            with self.subTest(key=key):
                self.assertEqual(self.run_summary({'latest.json': data})[1],
                                 [f'latest.json: {key} missing or wrong type'])
        rows = {'regions[0].region_id': ['row'], 'regions[0].status': [{'region_id': 'a', 'status': 1, 'issues': []}]}
        for key, regions in rows.items():
            with self.subTest(key=key):
                self.assertEqual(self.run_summary({'intelligence-health.json': {'regions': regions}})[1],
                                 [f'intelligence-health.json: {key} missing or wrong type'])

    def test_undecodable_or_too_deep_bytes_are_unreadable(self):
        for raw in (b'\xff\xfe{"regions": []}', b'[' * 200000):
            with self.subTest(raw=raw[:8]):
                self.assertEqual(self.run_summary({'habitat-health.json': raw})[1], ['habitat-health.json is unreadable'])

    def test_text_from_a_damaged_file_is_never_printed(self):
        damaged = {'latest.json': {**LATEST, 'sources': {'secret text': {'name': 'secret text', 'status': None}}},
                   'intelligence-health.json': {'regions': [{'region_id': 'secret text', 'status': 'ok',
                                                             'issues': 'secret text'}]}}
        lines, failures, warnings = self.run_summary(damaged)
        self.assertEqual(failures, ['latest.json: sources[0].status missing or wrong type',
                                    'intelligence-health.json: regions[0].issues missing or wrong type'])
        self.assertNotIn('secret', json.dumps([lines, failures, warnings]))

    def test_main_writes_the_summary_then_exits_with_the_failure_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'out'
            root.mkdir()
            write(root, {'latest.json': b'{"completed_at": '})
            summary = Path(directory) / 'summary.md'
            argv = ['report_conditions.py', '--output', str(root), '--outcome', 'success']
            with mock.patch('sys.argv', argv), mock.patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), \
                    contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as raised:
                report_conditions.main()
            self.assertEqual(summary.read_text(),
                             '\n'.join(HEAD + INDEX_LINES + INTEL_LINES + HABITAT_LINES + tail(3)) + '\n')
        self.assertEqual(str(raised.exception.code), 'Publication failed or products missing: latest.json is unreadable')
        self.assertEqual(out.getvalue(), '::warning title=Degraded source::refresh-failed\n'
                                         '::warning title=Degraded source::sst-analysis\n')

    def test_wrongly_typed_optional_fields_are_ignored(self):
        odd = {'region_id': 'morro-bay', 'status': 'ok', 'issues': [], 'forecast_coverage': '6/7',
               'coverage_gaps': 'day-7', 'error_class': 5, 'error': 'secret text'}
        odd_latest = {**LATEST, 'sources': {'b1': {'name': 'Buoy 46011', 'status': 'ok', 'data': ['03:50Z']}}}
        lines, failures, _ = self.run_summary({'latest.json': odd_latest, 'regions/index.json': {'regions': [odd]}})
        self.assertEqual(failures, [])
        self.assertEqual(lines[2:6], ['Buoy feed collected 2026-11-02T04:00Z', '- Buoy 46011: ok; observed unavailable',
                                      '\n### regions/index.json', '- morro-bay: ok'])
        self.assertEqual(lines[6], '\n### intelligence-health.json')


if __name__ == '__main__':
    unittest.main()

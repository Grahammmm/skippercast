"""Draft source checks must be isolated from published regional feeds; regions fail independently."""
import json
import tempfile
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import refresh_regions
from scripts.refresh_regions import critical_regions, gate, refresh
from skippercast.platform.contracts import REPO, load_region


class DraftRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (REPO / 'var').mkdir(exist_ok=True)

    def test_one_draft_produces_only_its_local_receipt(self):
        draft = deepcopy(load_region('crescent-city'))
        draft['status'] = 'draft'
        with tempfile.TemporaryDirectory(dir=REPO / 'var') as directory:
            output = Path(directory)
            data = {'generated_at': '2026-09-24T00:00:00Z', 'completed_at': '2026-09-24T00:00:01Z',
                    'health': {'status': 'degraded', 'issues': ['fixture']},
                    'regulations': {}, 'sources': {}}
            with patch('scripts.refresh_regions.load_region', return_value=draft), \
                    patch('scripts.refresh_regions.daily', return_value=data) as collector, \
                    patch('scripts.refresh_regions.coverage', return_value={'status': 'fixture', 'species': {}}):
                rows = refresh('daily', output, only_region='crescent-city', include_drafts=True)
            self.assertEqual([row['region_id'] for row in rows], ['crescent-city'])
            self.assertEqual(collector.call_count, 1)
            self.assertTrue((output / 'regions/crescent-city/regulations-health.json').is_file())
            self.assertFalse((output / 'latest.json').exists())
            self.assertFalse((output / 'regions/morro-bay').exists())

    def test_draft_cannot_enter_regular_or_external_output(self):
        draft = deepcopy(load_region('crescent-city'))
        draft['status'] = 'draft'
        with tempfile.TemporaryDirectory(dir=REPO / 'var') as directory:
            with patch('scripts.refresh_regions.load_region', return_value=draft), \
                    self.assertRaisesRegex(ValueError, 'was not collected'):
                refresh('daily', Path(directory), only_region='crescent-city')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'unpublished var'):
                refresh('daily', Path(directory), only_region='crescent-city', include_drafts=True)


def live_feed(now, prior, region_id):
    return {'schema_version': 1, 'region_id': region_id, 'generated_at': '2026-09-28T12:00:00Z',
            'completed_at': '2026-09-28T12:00:05Z', 'sources': {}, 'health': {'status': 'ok', 'issues': []}}


def raising_for(*broken, error=ValueError):
    def collector(now, prior, region_id):
        if region_id in broken:
            raise error(f'{region_id} provider contract changed ' + 'x' * 1000)
        return live_feed(now, prior, region_id)
    return collector


class RegionIsolationTests(unittest.TestCase):
    """A raising collector fails only its own region; the job fails only for the default or a majority."""

    def run_live(self, collector, directory):
        output = Path(directory)
        with patch('scripts.refresh_regions.live', side_effect=collector), patch('builtins.print'):
            rows = refresh('live', output)
        return output, rows, json.loads((output / 'regions/index.json').read_text())

    def test_one_failing_region_is_recorded_and_the_others_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            output, rows, index = self.run_live(raising_for('crescent-city'), directory)
            by_id = {row['region_id']: row for row in index['regions']}
            failed = by_id['crescent-city']
            self.assertEqual((failed['status'], failed['error_class']), ('failed', 'ValueError'))
            self.assertTrue(failed['error'].startswith('crescent-city provider contract changed'))
            self.assertLessEqual(len(failed['error']), refresh_regions.ERROR_CHARS)
            self.assertFalse((output / 'regions/crescent-city').exists())
            published = [r for r in by_id if r != 'crescent-city']
            self.assertGreater(len(published), 5)
            for ident in published:
                self.assertEqual(by_id[ident]['status'], 'ok', ident)
                self.assertTrue((output / 'regions' / ident / 'latest.json').is_file(), ident)
            self.assertEqual(json.loads((output / 'latest.json').read_text())['region_id'], 'morro-bay')
            self.assertIsNone(gate(rows, critical_regions()))

    def test_default_region_failure_fails_the_job_but_others_still_write(self):
        with tempfile.TemporaryDirectory() as directory:
            output, rows, index = self.run_live(raising_for('morro-bay', error=KeyError), directory)
            self.assertIn('morro-bay', gate(rows, critical_regions()))
            self.assertFalse((output / 'latest.json').exists())  # no stale alias from a failed default
            self.assertTrue((output / 'regions/southern-california/latest.json').is_file())
            self.assertEqual({r['region_id']: r['error_class'] for r in index['regions'] if r['status'] == 'failed'},
                             {'morro-bay': 'KeyError'})

    def test_majority_failure_fails_the_job(self):
        regions = sorted(p.parent.name for p in (REPO / 'regions').glob('*/region.json'))
        broken = [r for r in regions if r != 'morro-bay'][:len(regions) // 2 + 1]
        with tempfile.TemporaryDirectory() as directory:
            _, rows, _ = self.run_live(raising_for(*broken), directory)
            self.assertEqual(gate(rows, critical_regions()), f'{len(broken)} of {len(regions)} regions failed')
            _, rows, _ = self.run_live(raising_for(*broken[:len(regions) // 2]), directory)
            self.assertIsNone(gate(rows, critical_regions()))

    def test_critical_regions_are_the_default_active_or_requested_one(self):
        self.assertEqual(critical_regions(), {'morro-bay'})
        self.assertEqual(critical_regions('crescent-city'), {'crescent-city'})

    def test_command_line_exit_status(self):
        with tempfile.TemporaryDirectory() as directory, patch('builtins.print'):
            with patch('scripts.refresh_regions.live', side_effect=raising_for('crescent-city')):
                self.assertEqual(refresh_regions.main(['live', '--output', directory]), 0)
            with patch('scripts.refresh_regions.live', side_effect=raising_for('morro-bay')):
                self.assertEqual(refresh_regions.main(['live', '--output', directory]), 1)

    def test_intelligence_failures_are_isolated_too(self):
        def run(ident, output, previous_root, now):
            if ident == 'big-sur-coast':
                raise RuntimeError('grid decode failed')
            return {'completed_at': '2026-09-28T12:00:05Z', 'health': {'status': 'ok', 'issues': []}}
        with tempfile.TemporaryDirectory() as directory, \
                patch('skippercast.pipeline.intelligence.run', side_effect=run), patch('builtins.print'):
            rows = refresh('intelligence', Path(directory))
            health = json.loads((Path(directory) / 'intelligence-health.json').read_text())
        self.assertEqual([r['region_id'] for r in health['regions'] if r['status'] == 'failed'], ['big-sur-coast'])
        self.assertIsNone(gate(rows, critical_regions()))


    def test_cycle_report_names_the_failed_region(self):
        from scripts.report_conditions import summarize
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'regions').mkdir()
            (root / 'latest.json').write_text(json.dumps({'completed_at': 'x', 'sources': {}, 'health': {'issues': []}}))
            row = refresh_regions.failed_row('crescent-city', ValueError('bad'))
            (root / 'regions/index.json').write_text(json.dumps({'regions': [row]}))
            for name in ('intelligence-health.json', 'habitat-health.json'):
                (root / name).write_text(json.dumps({'regions': []}))
            lines, failures, warnings = summarize(root, 'success')
        self.assertEqual(failures, [])
        self.assertIn('refresh-failed', warnings)
        self.assertTrue(any('Refresh failed (ValueError): bad' in line for line in lines))


if __name__ == '__main__':
    unittest.main()

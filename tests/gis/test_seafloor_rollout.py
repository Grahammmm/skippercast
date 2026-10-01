"""Rollout advances new reaches, preserves failures, and never claims stale success."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import jobs, rollout, state_cache
from skippercast.seafloor.io import sha256
from tests.gis.test_seafloor_publish import Bucket


class RolloutTests(unittest.TestCase):
    def test_missing_or_unsafe_batch_cannot_reuse_a_shared_result(self):
        for batch in ('', '-', '../old', 'a/b'):
            with self.subTest(batch=batch), self.assertRaises(ValueError):
                jobs.batch_key(batch, 'r01')

    def test_plan_uses_reviewed_windows_without_counting_envelopes_as_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cells = [{'id': '3310:0:0', 'reach': 'r01', 'band_area_m2': 60000},
                     {'id': '3310:1:0', 'reach': 'r02', 'band_area_m2': 50000},
                     {'id': '3310:80:0', 'reach': 'r03', 'band_area_m2': 60000}]
            ref = root/'var/seafloor/reference/cells.json'
            atomic_json(ref, {'cells': cells})
            rows = [{'id': c['reach'], 'region': 'central', 'status': 'unassessed',
                     'tier1_km2': 0, 'tier2_km2': 0} for c in cells]
            atomic_json(root/'dist/data/seafloor-ledger.json', {'scope': 'central-coast',
                'reference_cells_sha256': sha256(ref), 'totals': {}, 'reaches': rows})
            atomic_json(root/'catalog/seafloor-screen.json', {'reviewed_reaches': []})
            t = Transformer.from_crs(3310, 4326, always_xy=True)
            bounds = [*t.transform(-10,-10), *t.transform(600,260)]
            usable = {'id': 'native', 'status': 'usable', 'kind': 'bathymetry',
                      'adapter_review': {'requested_bounds_wgs84': bounds}}
            candidate = {'id': 'envelope', 'kind': 'bathymetry', 'status': 'candidate',
                         'publisher': 'NOAA', 'title': 'unverified', 'url': 'https://example.org/data',
                         'hold_reason': 'unknown'}
            with patch.object(rollout, 'load_manifest', return_value={'surveys': [usable, candidate]}):
                result = rollout.plan(root, max_new=1)
                self.assertEqual(result['new_reaches'], ['r01'])
                self.assertEqual(result['reaches'][2]['action'], 'qualify-source')
                self.assertTrue(all(r['tier1_km2'] == 0 for r in result['reaches']))
                self.assertTrue(all(not r['screen_reviewed'] for r in result['reaches']))
                self.assertEqual(len(result['source_review_queue']), 1)
                self.assertEqual(rollout.plan(root, max_new=0)['new_reaches'], [])
                private = dict(usable, status='physical-only')
                with patch.object(rollout, 'load_manifest', return_value={'surveys': [private]}):
                    self.assertEqual(rollout.plan(root)['new_reaches'], [])
                    private_plan = rollout.plan(root, physical_only=True)
                    self.assertEqual(private_plan['new_reaches'], ['r01', 'r02'])
                    self.assertTrue(private_plan['physical_only'])
                    output = root/'var/seafloor/private-reaches/r01/cells.json'
                    atomic_json(output, {'cells': []})
                    atomic_json(output.parent/'run.json', {
                        'publication_prohibited': True,
                        'inputs': {'reference_cells_sha256': sha256(ref), 'sources': [private]},
                        'outputs': {'cells.json': sha256(output)},
                        'ledger_summary': {'processing_incomplete': False}})
                    advanced_private = rollout.plan(root, physical_only=True)
                    self.assertEqual(advanced_private['new_reaches'], ['r02'])
                    self.assertEqual(advanced_private['reaches'][0]['tier1_km2'], 0)
                    self.assertEqual(rollout.plan(root)['new_reaches'], [])
                    output.write_text('corrupt')
                    with self.assertRaisesRegex(ValueError, 'checksum'):
                        rollout.plan(root, physical_only=True)
                advanced = rollout.plan(root, max_new=1, progress={'r01': {'status': 'complete'}})
                self.assertEqual(advanced['new_reaches'], ['r02'])
                self.assertTrue(advanced['reaches'][0]['pending_ledger_merge'])
                self.assertEqual(advanced['reaches'][0]['tier1_km2'], 0)
                with self.assertRaisesRegex(ValueError, 'Unknown'):
                    rollout.plan(root, region='typo')
                ref.write_text('{}')
                with self.assertRaisesRegex(ValueError, 'Restore'):
                    rollout.plan(root)

    def test_worker_failure_saves_coverage_but_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); s3 = Bucket()
            def fails(*args, **kwargs):
                folder = root/'var/seafloor/reaches/r01'
                atomic_json(folder/'coverage-cells.json', {'cells': []})
                atomic_json(folder/'coverage-checkpoint.json', {'cells_sha256': sha256(folder/'coverage-cells.json'),
                    'ledger_summary': {'status': 'terrain-pending', 'tier1_km2': 4, 'tier2_km2': 0}})
                raise ValueError('Habitat window exceeds 20 million pixels')
            with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                 patch.object(state_cache, 'restore'), patch.object(state_cache, 'save'), \
                 patch.object(jobs, 'run', side_effect=fails):
                result = jobs.process(root, 'r01', 'run-1')
            self.assertEqual(result['status'], 'coverage-only')
            self.assertEqual(result['summary']['tier2_km2'], 0)
            self.assertEqual(result['reason'], 'habitat-window-limit')
            self.assertEqual(json.loads(s3.objects[jobs.batch_key('run-1','r01')]), result)
            with self.assertRaises(ValueError): jobs.batch_key('../escape', 'r01')

    def test_no_checkpoint_from_an_older_or_interrupted_run_is_credited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); s3 = Bucket()
            atomic_json(root/'var/seafloor/reaches/r01/coverage-checkpoint.json', {'old': True})
            with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                 patch.object(state_cache, 'restore', side_effect=ValueError('restore failed')):
                result = jobs.process(root, 'r01', 'run-2')
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('summary', result)

    def test_failed_source_review_is_reported_by_aggregation_without_stale_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); s3 = Bucket()
            (root/'var/seafloor').mkdir(parents=True)
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reaches': [
                {'id': 'r01', 'region': 'central', 'tier1_km2': 0, 'tier2_km2': 0}],
                'totals': {'tier2_km2': 0}})
            with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                 patch.object(state_cache, 'restore', return_value=True), \
                 patch.object(jobs, 'run', side_effect=ValueError('Normalized source differs from reviewed manifest')), \
                 patch.object(jobs, 'apply_ledger') as apply, patch.object(jobs, 'upload') as upload:
                worker = jobs.process(root, 'r01', 'source-failure')
                result = jobs.finish(root, {'include': [{'reach': 'r01', 'region': 'central'}]}, 'source-failure')
            self.assertEqual(worker['status'], 'failed')
            self.assertEqual(result['failures'], [{'reach': 'r01',
                'reason': 'normalized-source-review-mismatch', 'error_type': 'ValueError'}])
            apply.assert_not_called(); upload.assert_not_called()

    def test_missing_current_batch_does_not_block_another_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); s3 = Bucket()
            rows = [{'id': 'r01', 'region': 'north', 'tier1_km2': 0, 'tier2_km2': 0},
                    {'id': 'r02', 'region': 'south', 'tier1_km2': 0, 'tier2_km2': 0}]
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reaches': rows, 'totals': {'tier2_km2': 0}})
            receipt = {'input_hash': 'current', 'ledger_summary': {'tier1_km2': 1, 'tier2_km2': .1}}
            atomic_json(root/'var/seafloor/reaches/r02/run.json', receipt)
            current = {'batch': 'batch-1', 'reach': 'r02', 'status': 'complete',
                       'input_hash': 'current', 'summary': receipt['ledger_summary']}
            s3.objects[jobs.batch_key('batch-1','r02')] = json.dumps(current).encode()
            # An old r01 success is deliberately irrelevant.
            s3.objects[jobs.batch_key('batch-old','r01')] = json.dumps(current).encode()
            with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                 patch.object(state_cache, 'restore', return_value=True), \
                 patch.object(jobs, 'apply_ledger') as apply, \
                 patch.object(jobs, 'upload', return_value={'key': 'south.pmtiles',
                    'manifest': {'region': 'south', 'status': 'ready'}}) as upload:
                result = jobs.finish(root, {'include': [{'reach': r['id'], 'region': r['region']} for r in rows]}, 'batch-1')
            apply.assert_called_once_with(root, 'r02', receipt['ledger_summary'])
            upload.assert_called_once_with('south', root=root)
            self.assertEqual(result['ready_regions'], ['south'])
            self.assertEqual(result['failures'][0]['reach'], 'r01')

    def test_reach_inventory_does_not_copy_unrelated_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for h in ('a'*64, 'b'*64):
                p = root/'var/seafloor/cache'/h/'source.bag'
                p.parent.mkdir(parents=True); p.write_bytes(b'native')
            atomic_json(root/'var/seafloor/reaches/r01/run.json', {'inputs': {
                'sources': [{'sha256': 'a'*64}], 'substrate_bindings': {}}})
            paths = state_cache.reach_paths(root, 'r01')
            self.assertTrue(any('a'*64 in str(p) for p in paths))
            self.assertFalse(any('b'*64 in str(p) for p in paths))

    def test_regional_finish_does_not_restore_or_wait_for_another_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); s3 = Bucket()
            rows = [{'id': 'r01', 'region': 'north', 'tier1_km2': 0, 'tier2_km2': 0},
                    {'id': 'r02', 'region': 'south', 'tier1_km2': 0, 'tier2_km2': 0}]
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reaches': rows, 'totals': {'tier2_km2': 0}})
            receipt = {'input_hash': 'current', 'ledger_summary': {'tier1_km2': 1, 'tier2_km2': .1}}
            atomic_json(root/'var/seafloor/reaches/r02/run.json', receipt)
            current = {'batch': 'batch-1', 'reach': 'r02', 'status': 'complete',
                       'input_hash': 'current', 'summary': receipt['ledger_summary']}
            s3.objects[jobs.batch_key('batch-1', 'r02')] = json.dumps(current).encode()
            matrix = {'include': [{'reach': r['id'], 'region': r['region']} for r in rows]}
            with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                 patch.object(state_cache, 'restore', return_value=True) as restore, \
                 patch.object(jobs, 'apply_ledger'), \
                 patch.object(jobs, 'upload', return_value={'key': 'south.pmtiles',
                    'manifest': {'region': 'south', 'status': 'ready'}}) as upload:
                result = jobs.finish(root, matrix, 'batch-1', region='south')
                self.assertEqual(result['failures'], [])
                self.assertEqual(result['ready_regions'], ['south'])
                upload.assert_called_once_with('south', root=root)
                self.assertFalse(any(c.args[-1] == 'r01' for c in restore.call_args_list))
                restore.assert_any_call(s3, 'b', root, 'r02', include_cache=True)
                with self.assertRaisesRegex(ValueError, 'absent'):
                    jobs.finish(root, matrix, 'batch-1', region='absent')
            # Retrying bookkeeping consumes the same checked worker result;
            # it must not restore source archives or attempt publication.
            with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                 patch.object(state_cache, 'restore', return_value=True) as restore, \
                 patch.object(jobs, 'apply_ledger'), patch.object(jobs, 'upload') as upload:
                result = jobs.finish(root, matrix, 'batch-1', region='south', ledger_only=True)
                restore.assert_any_call(s3, 'b', root, 'r02', include_cache=False)
                upload.assert_not_called()
                self.assertEqual(result['ready_regions'], ['south'])

    def test_ledger_only_reports_failed_or_missing_current_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); s3 = Bucket()
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reaches': [], 'totals': {'tier2_km2': 0}})
            (root/'var/seafloor').mkdir(parents=True)
            receipt = {'input_hash': 'current', 'ledger_summary': {'tier1_km2': 1, 'tier2_km2': .1}}
            atomic_json(root/'var/seafloor/reaches/r01/run.json', receipt)
            s3.objects[jobs.batch_key('batch-1', 'r01')] = json.dumps({'batch': 'batch-1', 'reach': 'r01', 'status': 'complete', 'input_hash': 'current', 'summary': receipt['ledger_summary']}).encode()
            matrix = {'include': [{'reach': 'r01', 'region': 'south'}]}
            failed = {'version': 1, 'batch': 'batch-1', 'region': 'south',
                      'published': [], 'ready_regions': [], 'held_regions': [],
                      'failures': [{'region': 'south', 'reason': 'publication failed'}]}
            key = jobs.publication_key('batch-1', 'south')
            for document in (failed, dict(failed, batch='old'), None):
                if document is None: s3.objects.pop(key, None)
                else: s3.objects[key] = json.dumps(document).encode()
                with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                     patch.object(state_cache, 'restore', return_value=True), \
                     patch.object(jobs, 'apply_ledger'), \
                     patch.object(jobs, 'upload') as upload:
                    result = jobs.finish(root, matrix, 'batch-1', ledger_only=True)
                self.assertTrue(any(f.get('region') == 'south' for f in result['failures']))
                self.assertEqual(result['ready_regions'], [])
                upload.assert_not_called()
                body = (root/'var/seafloor/ledger-pr.md').read_text()
                self.assertIn('south', body)
                self.assertIn('not proof of live publication', body)
                self.assertNotIn('Validation: current source hashes, full-polygon', body)

    def test_shared_restore_clears_previous_failure_only_after_inventory_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); s3 = Bucket()
            failure = root/'var/seafloor/screen/refresh-failure.json'
            atomic_json(failure, {'failed': True})
            s3.objects['seafloor-cache/state/shared.json'] = json.dumps({'version': 1, 'scope': 'shared', 'files': []}).encode()
            self.assertTrue(state_cache.restore(s3, 'b', root, 'shared'))
            self.assertFalse(failure.exists())


if __name__ == '__main__':
    unittest.main()

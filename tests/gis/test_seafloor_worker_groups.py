"""Reduce runner starts without losing reach work, isolation or failure receipts."""
from contextlib import redirect_stdout
from io import StringIO
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import jobs, state_cache
from tests.gis.test_seafloor_publish import Bucket


class WorkerGroupTests(unittest.TestCase):
    def test_all_assignments_appear_once_and_regions_never_mix(self):
        rows = [{'reach': f'{region}-r{n:02}', 'region': region}
                for region, count in [('north', 8), ('central', 6), ('south', 4)]
                for n in range(count)]
        original = json.dumps(rows)
        grouped = jobs.worker_groups({'include': rows})['include']
        self.assertEqual(len(grouped), 7)  # 18 runner starts become seven.
        flattened = [{'reach': reach, 'region': row['region']}
                     for row in grouped for reach in row['reaches']]
        self.assertEqual(flattened, rows)
        self.assertTrue(all(1 <= len(row['reaches']) <= 3 for row in grouped))
        self.assertEqual(json.dumps(rows), original)
        self.assertEqual(jobs.worker_groups({'include': []}), {'include': []})
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            jobs.worker_groups({'include': rows + [rows[0]]})

    def root(self, folder):
        root = Path(folder)
        atomic_json(root/'catalog/reaches.json', {'reaches': [
            {'id': 'r01', 'region': 'north'}, {'id': 'r02', 'region': 'north'},
            {'id': 'r03', 'region': 'north'}, {'id': 'r04', 'region': 'south'}]})
        return root

    def test_invalid_group_rejected_before_any_processing_or_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            invalid = [[], ['r01'] * 2, ['r01', 'r02', 'r03', 'r04'],
                       ['r01', 'r04'], ['unknown'], ['../r01'], 'r01', [None]]
            for reaches in invalid:
                with self.subTest(reaches=reaches), patch.object(jobs, 'group_member') as process:
                    with self.assertRaises(ValueError):
                        jobs.process_group(root, reaches, 'north', 'batch-1')
                    process.assert_not_called()
            with patch.object(jobs, 'group_member') as process:
                with self.assertRaises(ValueError):
                    jobs.process_group(root, ['r01'], 'north', '../old')
                process.assert_not_called()

    def test_failed_computation_retains_each_receipt_and_runs_the_next_reach(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            bucket, visited = Bucket(), []

            def run(reach, **kwargs):
                visited.append(reach)
                if reach == 'r02':
                    raise ValueError('broken source')
                receipt = {'input_hash': 'checked-' + reach,
                           'ledger_summary': {'tier1_km2': 1, 'tier2_km2': 0.1}}
                atomic_json(root/f'var/seafloor/reaches/{reach}/run.json', receipt)
                atomic_json(root/f'var/seafloor/reaches/{reach}/atlas-comparison.json', {})
                return receipt, False

            with patch.object(jobs, 'credentials', return_value=(bucket, 'b')), \
                    patch.object(state_cache, 'restore'), patch.object(state_cache, 'save'), \
                    patch.object(state_cache, 'reach_paths', return_value=[]), \
                    patch.object(jobs, 'run', side_effect=run), \
                    patch.object(jobs, 'group_member', side_effect=jobs.process):
                result = jobs.process_group(root, ['r01', 'r02', 'r03'], 'north', 'batch-1')
            self.assertEqual(visited, ['r01', 'r02', 'r03'])
            self.assertFalse(result['complete'])
            for reach, expected in [('r01', 'complete'), ('r02', 'failed'), ('r03', 'complete')]:
                receipt = json.loads(bucket.objects[jobs.batch_key('batch-1', reach)])
                self.assertEqual(receipt['status'], expected)
                self.assertEqual(receipt['batch'], 'batch-1')
                self.assertEqual(receipt['reach'], reach)
            self.assertNotIn('seafloor-review/progress/r02.json', bucket.objects)

    def test_receipt_transport_failure_does_not_stop_later_reach_or_fake_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            done = lambda reach: {'reach': reach, 'batch': 'same-batch', 'status': 'complete'}
            with patch.object(jobs, 'group_member', side_effect=[
                    done('r01'), OSError('receipt upload failed'), done('r03')]) as process:
                result = jobs.process_group(root, ['r01', 'r02', 'r03'], 'north', 'same-batch')
            self.assertEqual([call.args[1] for call in process.call_args_list], ['r01', 'r02', 'r03'])
            self.assertFalse(result['complete'])
            self.assertEqual(result['results'][1]['status'], 'failed')
            self.assertNotIn('summary', result['results'][1])
            self.assertEqual(result['results'][1]['error_type'], 'OSError')

    def test_cli_surfaces_partial_failure_and_keeps_explicit_retry_batch(self):
        for status in ['complete', 'coverage-only', 'failed']:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                root = self.root(folder)
                output = StringIO()
                with patch.object(jobs, 'REPO', root), patch.object(jobs, 'group_member',
                        return_value={'reach': 'r01', 'batch': 'original-1', 'status': status}) as process, \
                        patch('sys.argv', ['jobs', 'run-group', '--region', 'north',
                              '--reaches', '["r01"]', '--batch', 'original-1']), redirect_stdout(output):
                    if status == 'complete':
                        jobs.main()
                    else:
                        with self.assertRaises(SystemExit) as error:
                            jobs.main()
                        self.assertEqual(error.exception.code, 1)
                process.assert_called_once_with(root, 'r01', 'original-1')
                self.assertEqual(json.loads(output.getvalue())['complete'], status == 'complete')

    def test_member_has_its_own_process_timeout_and_checks_receipt_identity(self):
        root = Path('/bounded-worker')
        result = {'reach': 'r01', 'batch': 'original-1', 'status': 'complete'}
        with patch.object(jobs.subprocess, 'run',
                return_value=subprocess.CompletedProcess([], 0, json.dumps(result))) as run:
            self.assertEqual(jobs.group_member(root, 'r01', 'original-1'), result)
        run.assert_called_once_with(
            [sys.executable, '-m', 'skippercast.seafloor.jobs', 'run',
             '--reach', 'r01', '--batch', 'original-1'],
            cwd=root, stdout=subprocess.PIPE, text=True, check=True, timeout=3600)
        result['batch'] = 'stale'
        with patch.object(jobs.subprocess, 'run',
                return_value=subprocess.CompletedProcess([], 0, json.dumps(result))):
            with self.assertRaisesRegex(ValueError, 'identity'):
                jobs.group_member(root, 'r01', 'original-1')

    def test_timed_out_reach_does_not_consume_its_neighbors_time_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.root(folder)
            done = lambda reach: subprocess.CompletedProcess([], 0, json.dumps(
                {'reach': reach, 'batch': 'original-1', 'status': 'complete'}))
            with patch.object(jobs.subprocess, 'run', side_effect=[
                    subprocess.TimeoutExpired('worker', 3600), done('r02'), done('r03')]) as run:
                result = jobs.process_group(root, ['r01', 'r02', 'r03'], 'north', 'original-1')
            self.assertFalse(result['complete'])
            self.assertEqual([row['status'] for row in result['results']],
                             ['failed', 'complete', 'complete'])
            self.assertEqual([call.kwargs['timeout'] for call in run.call_args_list], [3600] * 3)

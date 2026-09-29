"""Run manifests for scripts/refresh_regions.py, their report table and their R2 upload (offline)."""
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import publish_r2, refresh_regions
from skippercast import report, runs
from skippercast.platform.contracts import REPO

FEEDS = REPO / 'tests/fixtures/feeds'
ENV = {'GITHUB_RUN_ID': '9001', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'd' * 40}


def live_collector(*broken):
    sample = json.loads((FEEDS / 'live-latest.json').read_text())

    def collector(now, prior, region_id):
        if region_id in broken:
            raise ValueError(f'{region_id} buoy contract changed')
        document = {**sample, 'region_id': region_id}
        if region_id == 'crescent-city':  # one stale source in a degraded region
            first = next(iter(document['sources']))
            document['sources'] = {**document['sources'],
                                   first: {**document['sources'][first], 'status': 'stale', 'issue': 'buoy 3 h old'}}
            document['health'] = {'status': 'degraded', 'issues': [first]}
        return document
    return collector


class RefreshManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)  # jobs run from the checkout with relative paths; manifests store them relative
        self.output, self.runs = self.root / 'live', self.root / 'runs'

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def main(self, *args, collector=None):
        with patch.dict(os.environ, ENV), patch('scripts.refresh_regions.live', side_effect=collector or live_collector()), \
                patch('builtins.print'), redirect_stderr(io.StringIO()):
            return refresh_regions.main(['live', '--output', str(self.output), *args])

    def manifest(self):
        return json.loads((self.runs / 'refresh-live/9001.json').read_text())

    def test_off_by_default(self):
        with patch.object(refresh_regions, 'RUNS', self.runs):
            self.assertEqual(self.main(), 0)
        self.assertFalse(self.runs.exists())

    def test_flag_without_a_directory_uses_var_runs(self):
        with patch.object(refresh_regions, 'RUNS', self.runs):
            self.assertEqual(self.main('--run-manifest'), 0)
        self.assertTrue((self.runs / 'refresh-live/9001.json').is_file())

    def test_records_regions_sources_files_and_exit_status(self):
        self.assertEqual(self.main('--run-manifest', str(self.runs), collector=live_collector('big-sur-coast')), 0)
        m = runs.validate(self.manifest())
        self.assertEqual((m['job'], m['run_id'], m['git_sha'], m['exit_code']), ('refresh-live', '9001', 'd' * 40, 0))
        self.assertEqual(m['status'], 'degraded')  # a failed and a degraded region, but the gate passed
        self.assertIsNone(m['error'])
        regions = m['regions']
        self.assertEqual(len(regions), len(list((REPO / 'regions').glob('*/region.json'))))
        self.assertEqual((regions['big-sur-coast']['status'], regions['big-sur-coast']['error_class']), ('failed', 'ValueError'))
        self.assertIn('buoy contract changed', regions['big-sur-coast']['error'])
        crescent = regions['crescent-city']
        self.assertEqual((crescent['status'], crescent['sources_ok'], crescent['sources_total']),
                         ('degraded', crescent['sources_total'] - 1, crescent['sources_total']))
        self.assertEqual(regions['morro-bay']['status'], 'ok')
        self.assertTrue(all(isinstance(r['duration_ms'], int) for r in regions.values()))
        stale = [k for k, v in m['sources'].items() if v['status'] == 'stale']
        self.assertEqual(len(stale), 1)
        self.assertTrue(stale[0].startswith('crescent-city/'))
        self.assertEqual(m['sources'][stale[0]]['detail'], 'buoy 3 h old')
        # Inputs: every region config read, with its hash; outputs: pointers written, never absolute paths.
        inputs = {f['path']: f for f in m['inputs']}
        config = REPO / 'regions/morro-bay/region.json'
        self.assertEqual(inputs['regions/morro-bay/region.json']['sha256'], hashlib.sha256(config.read_bytes()).hexdigest())
        outputs = [f['path'] for f in m['outputs']]
        self.assertIn('live/regions/morro-bay/latest.json', outputs)
        self.assertIn('live/regions/morro-bay/health.json', outputs)
        self.assertEqual(outputs[-1], 'live/regions/index.json')
        self.assertFalse(any('big-sur-coast/' in p for p in outputs))
        self.assertFalse(any(p.startswith('/') for p in outputs + list(inputs)))
        written = self.output / 'regions/morro-bay/latest.json'
        row = next(f for f in m['outputs'] if f['path'] == 'live/regions/morro-bay/latest.json')
        self.assertEqual(row['sha256'], hashlib.sha256(written.read_bytes()).hexdigest())

    def test_previous_feeds_are_recorded_as_inputs(self):
        previous = self.root / 'previous'
        (previous / 'regions/morro-bay').mkdir(parents=True)
        (previous / 'regions/morro-bay/latest.json').write_text((FEEDS / 'live-latest.json').read_text())
        self.main('--run-manifest', str(self.runs), '--previous-root', str(previous))
        paths = [f['path'] for f in self.manifest()['inputs']]
        self.assertEqual(paths.count('previous/regions/morro-bay/latest.json'), 1)

    def test_gate_failure_is_the_run_error(self):
        self.assertEqual(self.main('--run-manifest', str(self.runs), collector=live_collector('morro-bay')), 1)
        m = self.manifest()
        self.assertEqual((m['status'], m['exit_code'], m['error']['class']), ('failed', 1, 'RegionGate'))
        self.assertIn('morro-bay', m['error']['message'])

    def test_an_escaping_error_is_recorded_then_raised(self):
        with patch.object(refresh_regions, 'refresh', side_effect=OSError('disk full')), \
                self.assertRaises(OSError):
            self.main('--run-manifest', str(self.runs))
        m = self.manifest()
        self.assertEqual((m['status'], m['exit_code'], m['error']['class']), ('failed', 1, 'OSError'))

    def test_a_manifest_write_error_never_changes_the_exit_status(self):
        blocker = self.root / 'not-a-directory'
        blocker.write_text('x')
        self.assertEqual(self.main('--run-manifest', str(blocker)), 0)
        self.assertTrue((self.output / 'regions/index.json').is_file())

    def test_intelligence_manifest_records_its_outputs(self):
        def fake_run(ident, output, previous_root, now):
            data = {'sources': {'wcofs': {'status': 'ok'}, 'gefs-wind': {'status': 'failed', 'issue': 'HTTP 503',
                                                                          'requests': [{'http_status': 503}]}},
                    'completed_at': '2026-09-28T12:00:05Z',
                    'health': {'status': 'degraded', 'issues': ['gefs-wind'], 'coverage_gaps': []}}
            target = Path(output) / 'regions' / ident
            target.mkdir(parents=True, exist_ok=True)
            (target / 'intelligence.json').write_text('{}\n')
            return data
        with patch.dict(os.environ, ENV), patch('skippercast.pipeline.intelligence.run', side_effect=fake_run), \
                patch('builtins.print'), redirect_stderr(io.StringIO()):
            status = refresh_regions.main(['intelligence', '--output', str(self.output), '--only-region', 'morro-bay',
                                           '--run-manifest', str(self.runs)])
        self.assertEqual(status, 0)
        m = json.loads((self.runs / 'refresh-intelligence/9001.json').read_text())
        self.assertEqual(m['regions']['morro-bay']['sources_ok'], 1)
        self.assertEqual(m['sources']['morro-bay/gefs-wind']['http_status'], 503)
        outputs = [f['path'] for f in m['outputs']]
        self.assertEqual(outputs, ['live/regions/morro-bay/intelligence.json', 'live/intelligence-health.json'])

    def test_manifest_path_mirrors_the_r2_key(self):
        run = runs.RunManifest('refresh-live', '42', run_attempt=3)
        self.assertEqual(refresh_regions.manifest_path(run, Path('var/runs')), Path('var/runs/refresh-live/42-3.json'))
        self.assertEqual(run.r2_key(), 'runs/refresh-live/42-3.json')


class RegionReport(unittest.TestCase):
    def manifest(self):
        run = runs.RunManifest('refresh-live', '9001', git_sha='e' * 40)
        run.region('morro-bay', 'ok', sources_ok=3, sources_total=3, duration_ms=1200)
        run.region('crescent-city', 'degraded', sources_ok=2, sources_total=3, issues=['46027'])
        run.region('big-sur-coast', 'failed', error_class='ValueError', error='buoy | contract changed')
        run.source('morro-bay/46011', 'ok')
        run.source('crescent-city/46027', 'stale', detail='buoy 3 h old')
        run.finish(0)
        return run.to_dict()

    def test_region_table_lists_failed_first_and_only_non_ok_sources(self):
        text = report.render(self.manifest())
        self.assertIn('| Region | Status | Sources ok | Duration | Issues / error |', text)
        lines = text.splitlines()
        order = [line.split('|')[1].strip() for line in lines if line.startswith(('| big-sur', '| crescent-city |', '| morro-bay |'))]
        self.assertEqual(order, ['big-sur-coast', 'crescent-city', 'morro-bay'])
        self.assertIn('| big-sur-coast | ❌ failed | – | – | ValueError: buoy \\| contract changed |', text)
        self.assertIn('| crescent-city | ⚠️ degraded | 2/3 | – | 46027 |', text)
        self.assertIn('| morro-bay | ✅ ok | 3/3 | 1.2 s | – |', text)
        self.assertIn('Regions: 1 degraded, 1 failed, 1 ok', text)
        self.assertIn('| crescent-city/46027 | stale | – | buoy 3 h old |', text)
        self.assertNotIn('| morro-bay/46011', text)
        self.assertIn('Sources: 1 ok, 1 stale', text)

    def test_manifests_without_regions_render_as_before(self):
        run = runs.RunManifest('forecast-build', '1')
        run.source('gfs_global', 'ok')
        run.finish(0)
        document = run.to_dict()
        self.assertEqual(document['regions'], {})
        del document['regions']  # manifests written before this field existed
        text = report.render(document)
        self.assertNotIn('| Region |', text)
        self.assertIn('| gfs_global | ✅ ok |', text)

    def test_region_rows_must_have_a_status(self):
        document = self.manifest()
        document['regions']['morro-bay'] = {'sources_ok': 3}
        with self.assertRaises(ValueError):
            runs.validate(document)


class FakeS3:
    def __init__(self, short=False):
        self.objects, self.short, self.deleted = {}, short, []

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = (Body, kwargs)

    def head_object(self, Bucket, Key):
        body = self.objects[Key][0]
        return {'ContentLength': len(body) - (1 if self.short else 0)}

    def delete_objects(self, **kwargs):
        self.deleted.append(kwargs)


class UploadRunManifests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'runs'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, job='refresh-live', run_id='9001', attempt=None):
        run = runs.RunManifest(job, run_id, run_attempt=attempt)
        run.finish(0)
        path = refresh_regions.manifest_path(run, self.root)
        run.write(path)
        return path

    def test_uploads_each_manifest_to_its_key_and_never_deletes(self):
        self.write()
        self.write('refresh-daily', '9002', attempt=2)
        s3 = FakeS3()
        message = publish_r2.upload_run_manifests(s3, 'bucket', self.root)
        self.assertEqual(sorted(s3.objects), ['runs/refresh-daily/9002-2.json', 'runs/refresh-live/9001.json'])
        self.assertEqual(s3.objects['runs/refresh-live/9001.json'][1]['ContentType'], 'application/json')
        self.assertEqual(s3.deleted, [])
        self.assertIn('2 run manifest(s) uploaded and verified', message)

    def test_missing_directory_uploads_nothing(self):
        self.assertIn('0 run manifest(s)', publish_r2.upload_run_manifests(FakeS3(), 'bucket', self.root))

    def test_read_back_mismatch_fails(self):
        self.write()
        with self.assertRaisesRegex(RuntimeError, 'read-back mismatch'):
            publish_r2.upload_run_manifests(FakeS3(short=True), 'bucket', self.root)

    def test_rejects_stray_files_and_mismatched_jobs(self):
        path = self.write()
        (self.root / 'notes.txt').write_text('x')
        with self.assertRaisesRegex(ValueError, 'Not a run manifest path'):
            publish_r2.upload_run_manifests(FakeS3(), 'bucket', self.root)
        (self.root / 'notes.txt').unlink()
        (self.root / 'refresh-daily').mkdir()
        path.rename(self.root / 'refresh-daily/9001.json')
        with self.assertRaisesRegex(ValueError, 'does not match its folder'):
            publish_r2.upload_run_manifests(FakeS3(), 'bucket', self.root)

    def test_command_line_runs_prefix_uses_the_upload_function(self):
        self.write()
        seen = {}

        def upload(s3, bucket, source):
            seen['source'] = source
            return 'R2 fake/runs: 1'
        with patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN': 'token', 'CLOUDFLARE_ACCOUNT_ID': 'account'}), \
                patch.object(publish_r2, 'client', lambda t, a: object()), \
                patch.object(publish_r2, 'upload_run_manifests', upload), \
                patch.object(publish_r2, 'sync', side_effect=AssertionError('runs must not use sync')), \
                patch.object(sys, 'argv', ['publish_r2.py', str(self.root), 'runs']), patch('builtins.print'):
            self.assertEqual(publish_r2.run(), 0)
        self.assertEqual(seen['source'], str(self.root))


if __name__ == '__main__':
    unittest.main()

"""R2 publisher: change detection, ordering, deletion and the no-credentials no-op."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.publish_r2 import INDEX, plan, scan

ROOT = Path(__file__).resolve().parents[1]


class PlanTests(unittest.TestCase):
    def test_changed_data_before_pointers_and_removals(self):
        local = {'regions/a/latest.json': '2', 'regions/a/tiles/x.json': '2', 'README.md': '1', 'manifest.json': '1'}
        remote = {'regions/a/latest.json': '1', 'regions/a/tiles/x.json': '1', 'README.md': '1', 'gone.json': '1'}
        uploads, deletions = plan(local, remote)
        self.assertEqual(uploads, ['regions/a/tiles/x.json', 'manifest.json', 'regions/a/latest.json'])
        self.assertEqual(deletions, ['gone.json'])

    def test_scan_skips_git_and_index(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / '.git').mkdir(); (root / '.git' / 'HEAD').write_text('x')
            (root / INDEX).write_text('{}')
            (root / 'a').mkdir(); (root / 'a' / 'b.json').write_text('{}')
            self.assertEqual(list(scan(root)), ['a/b.json'])

    def test_without_credentials_it_does_nothing(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('CLOUDFLARE_')}
        out = subprocess.run([sys.executable, str(ROOT / 'scripts/publish_r2.py'), str(ROOT / 'docs'), 'conditions'],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0)
        self.assertIn('R2 not configured', out.stdout)


@unittest.skipUnless(importlib.util.find_spec('moto') and importlib.util.find_spec('boto3'), 'moto/boto3 not installed')
class SyncTests(unittest.TestCase):
    def test_second_run_uploads_only_changes_and_deletes_removed(self):
        import boto3
        from moto import mock_aws
        from scripts.publish_r2 import sync
        with mock_aws(), tempfile.TemporaryDirectory() as d:
            s3 = boto3.client('s3', region_name='us-east-1')
            s3.create_bucket(Bucket='feeds')
            root = Path(d)
            (root / 'latest.json').write_text('{"v":1}')
            (root / 'tiles').mkdir()
            (root / 'tiles' / 'a.json').write_text('a'); (root / 'tiles' / 'b.json').write_text('b')
            self.assertIn('3 uploaded', sync(s3, 'feeds', root, 'forecasts'))
            (root / 'tiles' / 'b.json').unlink(); (root / 'latest.json').write_text('{"v":2}')
            self.assertIn('1 uploaded (1 pointers last), 1 removed, 1 unchanged', sync(s3, 'feeds', root, 'forecasts'))
            keys = sorted(o['Key'] for o in s3.list_objects_v2(Bucket='feeds')['Contents'])
            self.assertEqual(keys, ['forecasts/.r2-sync.json', 'forecasts/latest.json', 'forecasts/tiles/a.json'])
            obj = s3.get_object(Bucket='feeds', Key='forecasts/latest.json')
            self.assertEqual(json.loads(obj['Body'].read()), {'v': 2})
            self.assertEqual(obj['ContentType'], 'application/json')
            self.assertEqual(obj['CacheControl'], 'public, max-age=60')


class WiringTests(unittest.TestCase):
    def test_forecast_job_syncs_r2_even_when_tiles_are_unchanged(self):
        script = (Path(__file__).resolve().parents[1] / 'scripts' / 'publish_forecasts.sh').read_text()
        # The sync must sit after the if/else, or a new bucket stays empty until tiles change.
        self.assertGreater(script.index('publish_branch_r2.sh "$pub" forecasts'),
                           script.index('echo "Forecast tiles unchanged."'))


if __name__ == '__main__':
    unittest.main()

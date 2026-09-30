"""R2 publisher: change detection, ordering, deletion and the no-credentials no-op."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import publish_r2
from scripts.publish_r2 import INDEX, plan, scan
from tests._support import ROOT


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


class FailureTests(unittest.TestCase):
    """With credentials configured, any R2 error must fail the publishing job."""
    ENV = {'CLOUDFLARE_API_TOKEN': 'token', 'CLOUDFLARE_ACCOUNT_ID': 'account'}

    def test_upload_error_exits_non_zero_when_configured(self):
        def broken(token, account):
            raise RuntimeError('could not verify CLOUDFLARE_API_TOKEN')
        with patch.dict(os.environ, self.ENV), patch.object(publish_r2, 'client', broken), \
                patch.object(sys, 'argv', ['publish_r2.py', str(ROOT / 'docs'), 'conditions']), \
                patch('builtins.print') as printed:
            self.assertEqual(publish_r2.run(), 1)
        self.assertIn('::error title=R2 publish failed::RuntimeError', printed.call_args[0][0])

    def test_successful_sync_exits_zero(self):
        with patch.dict(os.environ, self.ENV), patch.object(publish_r2, 'client', lambda t, a: object()), \
                patch.object(publish_r2, 'sync', lambda *a: 'R2 fake: 0 uploaded'), \
                patch.object(sys, 'argv', ['publish_r2.py', str(ROOT / 'docs'), 'conditions']), \
                patch('builtins.print'):
            self.assertEqual(publish_r2.run(), 0)


class BranchScriptTests(unittest.TestCase):
    """publish_branch_r2.sh passes upload failures through; it no-ops without credentials."""

    def run_script(self, python_status, credentials=True):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tree, bin_dir = root / 'tree', root / 'bin'
            tree.mkdir(); bin_dir.mkdir()
            (tree / 'latest.json').write_text('{}')
            git = ['git', '-C', str(tree), '-c', 'user.name=t', '-c', 'user.email=t@t']
            subprocess.run(['git', 'init', '-q', str(tree)], check=True)
            subprocess.run(git + ['add', 'latest.json'], check=True)
            subprocess.run(git + ['commit', '-q', '-m', 'x'], check=True)
            fake = bin_dir / 'python'  # stands in for scripts/publish_r2.py
            fake.write_text(f'#!/bin/sh\nexit {python_status}\n'); fake.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if not k.startswith('CLOUDFLARE_')}
            env['PATH'] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            if credentials:
                env.update(FailureTests.ENV)
            return subprocess.run(['bash', str(ROOT / 'scripts/publish_branch_r2.sh'), str(tree), 'conditions'],
                                  capture_output=True, text=True, env=env, cwd=root, timeout=60)

    def test_upload_failure_fails_the_script(self):
        out = self.run_script(1)
        self.assertEqual(out.returncode, 1)
        self.assertIn('::error title=R2 publish::conditions upload failed', out.stdout)

    def test_upload_success_passes(self):
        self.assertEqual(self.run_script(0).returncode, 0)

    def test_without_credentials_it_skips(self):
        out = self.run_script(1, credentials=False)
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
        script = (ROOT / 'scripts' / 'publish_forecasts.sh').read_text()
        # The sync must sit after the if/else, or a new bucket stays empty until tiles change.
        self.assertGreater(script.index('publish_branch_r2.sh "$pub" forecasts'),
                           script.index('echo "Forecast tiles unchanged."'))

    def test_live_and_daily_jobs_verify_the_public_feed_after_r2(self):
        root = ROOT
        cycle = (root / 'scripts' / 'live_cycle.sh').read_text()
        self.assertGreater(cycle.index('verify_published_feed.py'),
                           cycle.index('publish_branch_r2.sh var/live-published conditions'))
        self.assertIn('if [ -n "${FEEDS_PUBLIC_BASE:-}" ]', cycle)
        daily = (root / '.github' / 'workflows' / 'daily-data.yml').read_text()
        self.assertGreater(daily.index('verify_published_feed.py'), daily.index('publish_branch_r2.sh var/published data'))
        self.assertIn("if: vars.FEEDS_PUBLIC_BASE != ''", daily)
        live = (root / '.github' / 'workflows' / 'live-conditions.yml').read_text()
        self.assertIn('FEEDS_PUBLIC_BASE: ${{ vars.FEEDS_PUBLIC_BASE }}', live)


if __name__ == '__main__':
    unittest.main()

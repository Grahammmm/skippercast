"""R2 lifecycle rules: run manifests expire, and history backstops never undercut the pipeline's retention."""
import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from scripts import r2_lifecycle

ROOT = Path(__file__).resolve().parents[1]


class LifecycleRuleTests(unittest.TestCase):
    def setUp(self):
        self.config = r2_lifecycle.rules(r2_lifecycle.region_ids())
        self.by_prefix = {rule['conditions'].get('prefix', ''): rule for rule in self.config['rules']}

    def days(self, prefix):
        return self.by_prefix[prefix]['deleteObjectsTransition']['condition']['maxAge'] / 86400

    def test_run_manifests_expire_after_seven_days(self):
        self.assertEqual(self.days('runs/'), 7)

    def test_every_region_history_and_verification_archive_has_a_backstop(self):
        regions = r2_lifecycle.region_ids()
        self.assertIn('morro-bay', regions)
        for region in regions:
            self.assertIn(f'data/regions/{region}/history/', self.by_prefix)
            self.assertIn(f'conditions/regions/{region}/verification-archive/', self.by_prefix)
        self.assertIn('data/history/', self.by_prefix)

    def test_backstops_expire_only_after_the_pipeline_stops_referencing_files(self):
        # refresh_regions.py and pipeline/__main__.py keep 90 days of daily history;
        # verification.py keeps 30 days of rows. R2 age counts from upload.
        for script in ('scripts/refresh_regions.py', 'src/skippercast/pipeline/__main__.py'):
            self.assertIn('timedelta(days=90)', (ROOT / script).read_text())
        self.assertIn('retention_days=30', (ROOT / 'src/skippercast/pipeline/verification.py').read_text())
        self.assertGreater(self.days('data/history/'), 90)
        self.assertGreater(self.days('data/regions/morro-bay/history/'), 90)
        self.assertGreater(self.days('conditions/regions/morro-bay/verification-archive/'), 30)

    def test_rules_are_well_formed_unique_and_within_the_r2_limit(self):
        ids = [rule['id'] for rule in self.config['rules']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(len(ids), 1000)
        for rule in self.config['rules']:
            self.assertTrue(rule['enabled'])
            prefix = rule['conditions'].get('prefix')
            if prefix is not None:
                self.assertTrue(prefix.endswith('/') and not prefix.startswith('/'), prefix)
                self.assertTrue(prefix.split('/')[0] in {'runs', 'data', 'conditions'}, prefix)
        # `lifecycle set` replaces R2's default rule, so it must be restated.
        default = next(rule for rule in self.config['rules'] if rule['id'] == 'Default Multipart Abort Rule')
        self.assertEqual(default['conditions'], {})
        self.assertEqual(default['abortMultipartUploadsTransition']['condition'], {'type': 'Age', 'maxAge': 7 * 86400})

    def test_no_rule_touches_live_pointers_or_tiles(self):
        for rule in self.config['rules']:
            if 'deleteObjectsTransition' not in rule:
                continue
            prefix = rule['conditions'].get('prefix', '')
            self.assertFalse(prefix in ('', 'conditions/', 'data/', 'forecasts/', 'tiles/', 'seafloor/'), prefix)
            self.assertTrue(prefix == 'runs/' or '/history/' in prefix or '/verification-archive/' in prefix, prefix)

    def test_print_changes_nothing(self):
        out = io.StringIO()
        with mock.patch('subprocess.run') as run, contextlib.redirect_stdout(out):
            self.assertEqual(r2_lifecycle.main(['--print']), 0)
        run.assert_not_called()
        self.assertEqual(json.loads(out.getvalue()), self.config)

    def test_without_credentials_it_skips(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('CLOUDFLARE_')}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch('subprocess.run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r2_lifecycle.main([]), 0)
        run.assert_not_called()

    def test_apply_sets_the_whole_configuration_with_wrangler(self):
        seen = {}

        def fake_run(command):
            seen['command'] = command
            seen['config'] = json.loads(Path(command[command.index('--file') + 1]).read_text())
            return mock.Mock(returncode=0)
        env = {'CLOUDFLARE_API_TOKEN': 't', 'CLOUDFLARE_ACCOUNT_ID': 'a'}
        with mock.patch.dict(os.environ, env), mock.patch('subprocess.run', fake_run), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r2_lifecycle.main(['--bucket', 'feeds']), 0)
        self.assertEqual(seen['command'][:3], ['npx', '--yes', 'wrangler@4.142.0'])
        self.assertEqual(seen['command'][3:7], ['r2', 'bucket', 'lifecycle', 'set'])
        self.assertIn('feeds', seen['command'])
        self.assertIn('--force', seen['command'])
        self.assertEqual(seen['config'], self.config)

    def test_deploy_applies_the_rules(self):
        deploy = (ROOT / 'scripts' / 'cloudflare_deploy.sh').read_text()
        self.assertIn('scripts/r2_lifecycle.py --bucket "$BUCKET"', deploy)


if __name__ == '__main__':
    unittest.main()

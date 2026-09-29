"""Reference integration of run manifests and structured logs: the forecast tile builder."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast import report, runs
from skippercast.forecast import build


def fake_build_one(model, output, previous, force, log):
    if model.id == 'ecmwf_wam':
        raise RuntimeError('no complete cycle published in the last 48 hours')
    target = output / model.id
    target.mkdir(parents=True, exist_ok=True)
    manifest = {'cycle_iso': '2026-09-28T18:00:00Z', 'built_at': '2026-09-28T22:37:31Z', 'tiles': ['35_-121', '36_-122']}
    (target / 'manifest.json').write_text(json.dumps(manifest))
    log(f'{model.id}: built')
    return manifest, 'built'


class ForecastRunManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        previous = self.root / 'published/ecmwf_wam'
        previous.mkdir(parents=True)
        (previous / 'manifest.json').write_text('{"cycle": 1}')

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()
        root = logging.getLogger('skippercast')
        for handler in list(root.handlers):
            root.removeHandler(handler)

    def run_main(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        env = {'GITHUB_RUN_ID': '4242', 'GITHUB_SHA': 'd' * 40, 'SKIPPERCAST_LOG': 'json'}
        with mock.patch.object(build, 'build_one', fake_build_one), mock.patch.dict(os.environ, env), \
                redirect_stdout(out), redirect_stderr(err):
            build.main(['--output', 'out', '--previous', 'published', '--models', 'gfs_global,ecmwf_wam', *extra])
        return out.getvalue(), err.getvalue()

    def test_manifest_logs_and_unchanged_stdout(self):
        out, err = self.run_main('--run-manifest', 'runs/forecast-build.json')
        index = json.loads(out)  # publish_forecasts.sh still captures the index from stdout
        self.assertEqual(index['models']['ecmwf_wam'], {'status': 'failed', 'kept_previous': True,
                                                        'issue': 'no complete cycle published in the last 48 hours'})
        records = [json.loads(line) for line in err.splitlines()]
        self.assertTrue(all(r['job'] == 'forecast-build' and r['run_id'] == '4242' for r in records))
        self.assertIn('gfs_global: built', [r['msg'] for r in records])

        manifest = json.loads((self.root / 'runs/forecast-build.json').read_text())
        self.assertIs(runs.validate(manifest), manifest)
        self.assertEqual((manifest['job'], manifest['run_id'], manifest['git_sha'], manifest['exit_code'], manifest['status']),
                         ('forecast-build', '4242', 'd' * 40, 0, 'degraded'))
        self.assertEqual(manifest['sources']['gfs_global']['status'], 'ok')
        self.assertEqual(manifest['sources']['gfs_global']['tiles'], 2)
        self.assertEqual((manifest['sources']['ecmwf_wam']['status'], manifest['sources']['ecmwf_wam']['error_class'],
                          manifest['sources']['ecmwf_wam']['kept_previous']), ('failed', 'RuntimeError', True))
        self.assertEqual([f['path'] for f in manifest['inputs']], ['published/ecmwf_wam/manifest.json'])
        self.assertEqual([f['path'] for f in manifest['outputs']],
                         ['out/index.json', 'out/gfs_global/manifest.json', 'out/ecmwf_wam/manifest.json'])
        self.assertIn('| ecmwf_wam | ❌ failed |', report.render(manifest))

    def test_manifest_is_opt_in(self):
        self.run_main()
        self.assertFalse((self.root / 'runs').exists())

    def test_total_failure_still_writes_a_failed_manifest(self):
        def fail(model, output, previous, force, log):
            raise RuntimeError('S3 unavailable')
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(build, 'build_one', fail), mock.patch.dict(os.environ, {'SKIPPERCAST_LOG': 'json'}), \
                redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            build.main(['--output', 'out', '--models', 'gfs_global', '--run-manifest', 'runs/m.json'])
        self.assertEqual(stop.exception.code, 1)
        manifest = json.loads((self.root / 'runs/m.json').read_text())
        self.assertEqual((manifest['status'], manifest['exit_code']), ('failed', 1))


if __name__ == '__main__':
    unittest.main()

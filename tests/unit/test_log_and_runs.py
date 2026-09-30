"""Structured logging, run manifests and the step-summary report (stdlib only, offline)."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast import log, report, runs


class FakeTerminal(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class Logging(unittest.TestCase):
    def tearDown(self):
        root = logging.getLogger('skippercast')
        for handler in list(root.handlers):
            root.removeHandler(handler)

    def test_json_records_carry_run_context_and_extra_fields(self):
        stream = io.StringIO()
        logger = log.configure('daily', stream=stream, environ={'GITHUB_RUN_ID': '987', 'SKIPPERCAST_LOG': 'json'})
        logger.info('source checked', extra={'region': 'morro-bay', 'source_id': 'buoy-46011',
                                             'duration_ms': 812, 'http_status': 200})
        log.get_logger('pipeline.collect').warning('slow provider', extra={'source_id': 'mur-sst'})
        first, second = (json.loads(line) for line in stream.getvalue().splitlines())
        self.assertEqual(first['msg'], 'source checked')
        self.assertEqual(first['level'], 'info')
        self.assertEqual(first['logger'], 'skippercast.daily')
        self.assertEqual({k: first[k] for k in ('run_id', 'job', 'region', 'source_id', 'duration_ms', 'http_status')},
                         {'run_id': '987', 'job': 'daily', 'region': 'morro-bay', 'source_id': 'buoy-46011',
                          'duration_ms': 812, 'http_status': 200})
        self.assertRegex(first['ts'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')
        self.assertEqual((second['logger'], second['job'], second['run_id'], second['source_id']),
                         ('skippercast.pipeline.collect', 'daily', '987', 'mur-sst'))
        self.assertNotIn('http_status', second)

    def test_exceptions_record_their_class(self):
        stream = io.StringIO()
        logger = log.configure('live', stream=stream, environ={'SKIPPERCAST_LOG': 'json'})
        try:
            raise TimeoutError('NDBC did not answer')
        except TimeoutError:
            logger.exception('buoy failed', extra={'source_id': 'buoy-46028'})
        record = json.loads(stream.getvalue())
        self.assertEqual(record['error_class'], 'TimeoutError')
        self.assertIn('NDBC did not answer', record['exc'])

    def test_text_for_terminals_or_when_asked(self):
        self.assertTrue(log.wants_text(FakeTerminal(True), {}))
        self.assertFalse(log.wants_text(FakeTerminal(False), {}))
        self.assertTrue(log.wants_text(FakeTerminal(False), {'SKIPPERCAST_LOG': 'text'}))
        self.assertFalse(log.wants_text(FakeTerminal(True), {'SKIPPERCAST_LOG': 'json'}))
        stream = io.StringIO()
        logger = log.configure('forecast-build', stream=stream, environ={'SKIPPERCAST_LOG': 'text'})
        logger.info('gfs_global: built', extra={'source_id': 'gfs_global', 'duration_ms': 1200})
        line = stream.getvalue().strip()
        self.assertRegex(line, r'^\d{2}:\d{2}:\d{2}Z INFO    forecast-build gfs_global: gfs_global: built \(duration_ms=1200\)$')

    def test_reconfiguring_replaces_the_handler(self):
        first, second = io.StringIO(), io.StringIO()
        log.configure('a', stream=first, environ={'SKIPPERCAST_LOG': 'json'})
        logger = log.configure('b', stream=second, environ={'SKIPPERCAST_LOG': 'json'})
        logger.info('once')
        self.assertEqual(first.getvalue(), '')
        self.assertEqual(len(second.getvalue().splitlines()), 1)

    def test_run_id_matches_feed_publication_or_is_local(self):
        self.assertEqual(log.run_id({'GITHUB_RUN_ID': '12345'}), '12345')
        self.assertRegex(log.run_id({}), r'^local-\d{8}T\d{6}Z$')


class Manifests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def start(self, **env):
        environ = {'GITHUB_RUN_ID': '555', 'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_SHA': 'a' * 40, **env}
        return runs.RunManifest.start('forecast-build', environ=environ)

    def test_manifest_records_files_sources_and_status(self):
        (self.root / 'in.json').write_text('{"a":1}\n')
        (self.root / 'out').mkdir()
        (self.root / 'out/index.json').write_text('{"b":2}\n')
        run = self.start()
        run.add_input(self.root / 'in.json')
        self.assertIsNone(run.add_input(self.root / 'missing.json', optional=True))
        with self.assertRaises(FileNotFoundError):
            run.add_input(self.root / 'missing.json')
        run.source('gfs_global', 'ok', duration_ms=10, detail='built')
        run.source('ecmwf_wam', 'failed', error_class='RuntimeError', detail='x' * 900, http_status=None)
        run.add_output('out/index.json')
        run.finish(0)
        written = run.write(self.root / 'runs/manifest.json')
        document = json.loads((self.root / 'runs/manifest.json').read_text())
        self.assertEqual(written['bytes'], (self.root / 'runs/manifest.json').stat().st_size)
        self.assertEqual((document['job'], document['run_id'], document['run_attempt'], document['git_sha']),
                         ('forecast-build', '555', 2, 'a' * 40))
        self.assertEqual(document['status'], 'degraded')  # exit 0 but a source failed
        self.assertEqual(document['exit_code'], 0)
        self.assertEqual(document['inputs'], [{'path': 'in.json', 'bytes': 8,
                                               'sha256': hashlib.sha256(b'{"a":1}\n').hexdigest()}])
        self.assertEqual(document['outputs'][0]['path'], 'out/index.json')
        self.assertEqual(len(document['sources']['ecmwf_wam']['detail']), runs.ERROR_CHARS)
        self.assertNotIn('http_status', document['sources']['ecmwf_wam'])
        self.assertRegex(document['started_at'], r'Z$')
        self.assertGreaterEqual(document['duration_ms'], 0)
        self.assertEqual(run.r2_key(), 'runs/forecast-build/555-2.json')
        self.assertIs(runs.validate(document), document)

    def test_paths_never_leak_machine_locations(self):
        outside = tempfile.NamedTemporaryFile(delete=False, dir=tempfile.gettempdir(), suffix='.json')
        outside.write(b'{}')
        outside.close()
        try:
            self.assertEqual(runs.public_path(outside.name, roots=[self.root]), Path(outside.name).name)
        finally:
            os.unlink(outside.name)
        self.assertEqual(runs.public_path(self.root / 'a/b.json'), 'a/b.json')
        self.assertEqual(runs.public_path('var/x.json'), 'var/x.json')

    def test_status_rules(self):
        self.assertEqual(self.start().finish(0).status, 'ok')
        self.assertEqual(self.start().finish(1).status, 'failed')
        run = self.start()
        run.source('a', 'ok')
        self.assertEqual(run.finish(0).status, 'ok')
        with self.assertRaises(ValueError):
            self.start().finish(0, status='fine')

    def test_context_manager_records_an_escaping_error(self):
        with self.assertRaises(KeyError):
            with self.start() as run:
                raise KeyError('model')
        self.assertEqual((run.status, run.exit_code, run.error['class']), ('failed', 1, 'KeyError'))
        with self.assertRaises(SystemExit):
            with self.start() as run:
                raise SystemExit(3)
        self.assertEqual((run.status, run.exit_code), ('failed', 3))
        with self.start() as run:
            pass
        self.assertEqual(run.status, 'ok')

    def test_local_run_without_actions_environment(self):
        with mock.patch.object(runs, 'git_sha', return_value=None):
            run = runs.RunManifest.start('demo', environ={})
        self.assertRegex(run.run_id, r'^local-')
        self.assertIsNone(run.run_attempt)
        self.assertEqual(run.r2_key(), f'runs/demo/{run.run_id}.json')

    def test_git_sha_prefers_actions_and_falls_back_to_git(self):
        self.assertEqual(runs.git_sha({'GITHUB_SHA': 'b' * 40}), 'b' * 40)
        self.assertIsNone(runs.git_sha({}, root=self.root))  # not a repository


class Report(unittest.TestCase):
    def manifest(self):
        run = runs.RunManifest('daily', '777', run_attempt=1, git_sha='c' * 40)
        run.source('buoy-46011', 'ok', duration_ms=900)
        run.source('mur-sst', 'stale', detail='Source time | outside window', http_status=200)
        run.finish(0)
        return run.to_dict()

    def test_render_is_a_step_summary_table(self):
        text = report.render(self.manifest())
        self.assertTrue(text.startswith('### daily: ⚠️ degraded\n'))
        self.assertIn('| 777 (attempt 1) | cccccccccccc |', text)
        self.assertIn('| Source | Status | Duration | Detail |', text)
        lines = text.splitlines()
        stale = next(line for line in lines if line.startswith('| mur-sst'))
        self.assertIn('Source time \\| outside window; http_status: 200', stale)
        self.assertLess(lines.index(stale), next(i for i, l in enumerate(lines) if l.startswith('| buoy-46011')))
        self.assertIn('Sources: 1 ok, 1 stale', text)

    def test_failed_run_shows_its_error(self):
        run = runs.RunManifest('live', '1')
        run.finish(1, error=ValueError('Invalid feed schema'))
        text = report.render(run.to_dict())
        self.assertIn('❌ failed', text)
        self.assertIn('**Error:** `ValueError` Invalid feed schema', text)

    def test_cli_prints_and_appends_to_the_step_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, summary = Path(tmp) / 'run.json', Path(tmp) / 'summary.md'
            path.write_text(json.dumps(self.manifest()))
            (Path(tmp) / 'bad.json').write_text('{"schema_version": 2}')
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), \
                    redirect_stdout(out), redirect_stderr(err):
                status = report.main(['--append-summary', str(path), str(Path(tmp) / 'bad.json')])
            self.assertEqual(status, 1)
            self.assertIn('### daily', out.getvalue())
            self.assertIn('### daily', summary.read_text())
            self.assertIn('Not a SkipperCast run manifest', err.getvalue())


if __name__ == '__main__':
    unittest.main()

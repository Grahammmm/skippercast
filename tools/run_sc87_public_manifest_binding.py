#!/usr/bin/env python3
"""Offline SC87 acceptance runner. Guards apply only in this script process."""
import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
import uuid

BASE = 'a1f648632e64561d82dcbeb20d9bda19f812560a'
OWNED = ('src/skippercast/seafloor/verify.py',
         'tests/unit/test_sc87_public_manifest_binding.py',
         'tests/fixtures/sc87-public-manifest-binding/manifest.json',
         'tools/run_sc87_public_manifest_binding.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def below(path, root):
    return path == root or root in path.parents


class OfflineGuard:
    """Defense in depth, not a hostile-code sandbox.

    Fixture access is confined to the fresh synthetic tree. Normal source and
    installed runtime imports are read-only. No product network or child calls.
    """
    def __init__(self, repo, run, manifest):
        self.repo, self.run, self.manifest = repo, run, manifest
        self.unexpected = []
        self.hashing_inputs = False

    def reason(self, event, args):
        if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn')) or event in (
                'os.system', 'os.fork', 'os.forkpty', 'pty.spawn'):
            return 'network/child forbidden'
        if event == 'open':
            name, mode, flags = args
            if isinstance(name, int):
                return None
            path = Path(os.fsdecode(name)).absolute()
            resolved = path.resolve()
            writing = (any(c in (mode or '') for c in 'wax+') or
                       bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if writing and not below(resolved, self.run):
                return 'write outside unique run'
            if below(path, self.repo / 'tests' / 'fixtures') and not self.hashing_inputs:
                return 'authored fixtures must be copied before imports'
            if any(below(resolved, self.repo / p) for p in ('var', 'dist', 'catalog', 'regions')):
                return 'non-synthetic product data'
            # Normal installed dependency files and repository code are read-only.
            if not writing and not (below(resolved, self.run) or below(resolved, self.repo)
                    or resolved == self.manifest
                    or any(below(resolved, Path(p).resolve()) for p in (
                        sys.base_prefix, sys.prefix, '/usr', '/lib', '/lib64'))
                    or str(resolved) in ('/dev/null', '/etc/localtime')):
                return 'read outside source/runtime/synthetic closure'
        if event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.rename', 'os.link', 'os.symlink'):
            paths = args[:2] if event in ('os.rename', 'os.link', 'os.symlink') else args[:1]
            for name in paths:
                if isinstance(name, (str, bytes, os.PathLike)):
                    if not below(Path(os.fsdecode(name)).resolve(), self.run):
                        return 'filesystem mutation outside run'
        return None

    def __call__(self, event, args):
        reason = self.reason(event, args)
        if reason:
            self.unexpected.append({'event': event, 'reason': reason})
            # unittest propagates KeyboardInterrupt instead of continuing peers.
            raise KeyboardInterrupt('SC87 OFFLINE STOP: ' + reason)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def row(self, test, outcome, detail=None):
        name = test.id()
        kind = ('isolation' if 'IsolationTests' in name else
                'negative-control' if 'NegativeControlTests' in name else
                'negative' if any(s in name for s in ('_served_', '_expected_', '_range_')) else
                'compatibility' if 'PublicationTests' in name or 'CompatibilityTests' in name else 'positive')
        self.rows.append({'test_id': name, 'assertion_class': kind, 'outcome': outcome, 'detail': detail})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.row(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.row(test, 'failed', self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.row(test, 'error', self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.row(test, 'skipped', reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('baseline', 'regression', 'compatibility', 'negative-control'), required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    repo = Path(__file__).resolve().parents[1]
    source_manifest = args.source_manifest.resolve()
    source = json.loads(source_manifest.read_text())
    root = repo.parent
    check(source['schema'] == 'agentorange.source-manifest/v1', 'manifest schema')
    check(Path(source['write_root']).resolve() == root and Path(source['repo']).resolve() == repo,
          'candidate root binding')
    check(source['head'] == BASE and git(repo, 'rev-parse', BASE) == BASE, 'base pin')
    check((repo / '.venv').resolve() == Path(source['runtime']['repo_venv']).resolve(), 'linked runtime')
    check(Path(sys.prefix).resolve() == (repo / '.venv').resolve(), 'interpreter runtime binding')
    scan_python = root.parent.parent / 'tools' / 'venv-fullsuite' / 'bin' / 'python3'
    check(Path(source['runtime']['credential_scan_python3']) == scan_python, 'scan runtime pin')
    check(source_manifest == root / 'SOURCE-MANIFEST.json', 'source manifest location')
    out = args.out.absolute()
    check(below(out.resolve(), root / 'out'), 'output must be below candidate out')
    check(out.resolve() == out, 'symlink output prefix')
    out.mkdir(parents=True, exist_ok=True)
    run = out / uuid.uuid4().hex
    run.mkdir(exist_ok=False)
    synthetic = run / 'synthetic'
    synthetic.mkdir()
    fixture = repo / OWNED[2]
    fixture_bytes = fixture.read_bytes()
    fixture_hash = hashlib.sha256(fixture_bytes).hexdigest()
    (synthetic / 'manifest.json').write_bytes(fixture_bytes)
    sentinel = synthetic / 'sentinel.txt'
    sentinel.write_text('synthetic unchanged sentinel\n')
    sentinel_before = digest(sentinel)
    sources = {name: digest(repo / name) for name in OWNED}
    sources['tests/gis/test_seafloor_publish.py'] = digest(repo / 'tests/gis/test_seafloor_publish.py')
    head = git(repo, 'rev-parse', 'HEAD')
    tracked = git(repo, 'status', '--porcelain', '--untracked-files=no')
    manifest_hash = digest(source_manifest)
    tempfile.tempdir = str(synthetic)
    sys.path[:0] = [str(repo / 'src'), str(repo)]
    guard = OfflineGuard(repo, run, source_manifest)
    sys.addaudithook(guard)
    stdout, stderr = io.StringIO(), io.StringIO()
    result = None
    fatal = None
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            # This is the first product import; redirect before contracts/defaults.
            from skippercast import paths
            paths.repo_root = lambda: synthetic
            from skippercast.platform import contracts
            check(contracts.REPO == synthetic, 'contracts redirect')
            module = importlib.import_module('tests.unit.test_sc87_public_manifest_binding')
            module.FIXTURE_ROOT = synthetic

            class IsolationTests(unittest.TestCase):
                def test_candidate_root_and_unique_output(self):
                    self.assertEqual(repo, Path(source['repo']).resolve())
                    self.assertEqual(run.parent, out)
                    self.assertEqual(contracts.REPO, synthetic)
                    self.assertEqual(tempfile.gettempdir(), str(synthetic))

                def test_allowed_synthetic_path_and_inert_denied_events(self):
                    allowed = synthetic / 'allowed.txt'
                    self.assertIsNone(guard.reason('open', (str(allowed), 'w', os.O_WRONLY)))
                    allowed.write_text('allowed synthetic event\n')
                    self.assertEqual(allowed.read_text(), 'allowed synthetic event\n')
                    # Pure decision tests only: no forbidden access or real syscall.
                    self.assertEqual(guard.reason('socket.connect', (None, ('inert.invalid', 0))), 'network/child forbidden')
                    self.assertEqual(guard.reason('subprocess.Popen', ('inert', [], None, None)), 'network/child forbidden')
                    self.assertEqual(guard.reason('open', (str(root / 'inert-denied-sentinel'), 'w', os.O_WRONLY)), 'write outside unique run')
                    self.assertEqual(digest(sentinel), sentinel_before)
                    self.assertEqual(digest(synthetic / 'manifest.json'), fixture_hash)

            loader = unittest.TestLoader()
            suite = unittest.TestSuite([loader.loadTestsFromTestCase(IsolationTests)])
            if args.suite == 'baseline':
                suite.addTest(module.RegressionTests('test_matching_manifest_and_exact_request'))
                suite.addTest(module.RegressionTests('test_served_wrong_region'))
            elif args.suite == 'regression':
                suite.addTest(loader.loadTestsFromTestCase(module.RegressionTests))
            elif args.suite == 'compatibility':
                original = importlib.import_module('tests.gis.test_seafloor_publish')
                suite.addTest(original.PublicationTests('test_public_probe_rejects_an_old_backend_or_wrong_archive'))
                for name in ('test_matching_manifest_and_exact_request', 'test_extra_metadata',
                             'test_minimum_archive_size', 'test_default_session_still_supported',
                             'test_request_bounds_and_options', 'test_target_region_mismatch_before_session',
                             'test_non_https_before_session'):
                    suite.addTest(module.CompatibilityTests(name))
            else:
                suite.addTest(loader.loadTestsFromTestCase(module.NegativeControlTests))
            result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=RecordingResult).run(suite)
        except (Exception, KeyboardInterrupt):
            fatal = traceback.format_exc()
            print(fatal, file=sys.stderr)
    # Only evidence hashing may reread authored fixture bytes; tested APIs always
    # consume the synthetic copy. Never enable writes outside the unique run.
    guard.hashing_inputs = True
    source_hashes_after = {name: digest(repo / name) for name in sources}
    guard.hashing_inputs = False
    inputs_unchanged = all(sources[name] == value for name, value in source_hashes_after.items())
    manifest_hash_after = digest(source_manifest)
    inputs_unchanged = inputs_unchanged and manifest_hash == manifest_hash_after
    inputs_unchanged = inputs_unchanged and digest(sentinel) == sentinel_before
    inputs_unchanged = inputs_unchanged and digest(synthetic / 'manifest.json') == fixture_hash
    exit_code = 0 if result is not None and result.wasSuccessful() and not result.skipped and not guard.unexpected and not fatal and inputs_unchanged else 1
    receipt = {
        'schema': 'sc87.acceptance/v1', 'argv': [sys.executable, *sys.argv],
        'cwd': str(Path.cwd()), 'interpreter': sys.executable, 'suite': args.suite,
        'head': head, 'admitted_base': BASE, 'tracked_status': tracked,
        'source_manifest_sha256': manifest_hash, 'source_manifest_sha256_after': manifest_hash_after,
        'source_hashes': sources,
        'source_hashes_after': source_hashes_after, 'inputs_unchanged': inputs_unchanged,
        'authored_fixture_sha256_before': fixture_hash,
        'authored_fixture_sha256_after': source_hashes_after[OWNED[2]],
        'input_sha256_before': fixture_hash, 'input_sha256_after': digest(synthetic / 'manifest.json'),
        'sentinel_sha256_before': sentinel_before, 'sentinel_sha256_after': digest(sentinel),
        'run_root': str(run), 'fixture_root_redirection': str(synthetic),
        'tests_run': result.testsRun if result else 0,
        'test_results': result.rows if result else [],
        'failures': len(result.failures) if result else 0,
        'errors': len(result.errors) if result else 0,
        'skips': len(result.skipped) if result else 0,
        'unexpected_guard_events': guard.unexpected, 'fatal': fatal, 'exit': exit_code,
    }
    for name, text in [('stdout.txt', stdout.getvalue()), ('stderr.txt', stderr.getvalue())]:
        path = run / name
        path.write_text(text)
        receipt[name + '_sha256'] = digest(path)
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(stderr.getvalue(), end='')
    print(stdout.getvalue(), end='')
    print(json.dumps({'receipt': str(run / 'receipt.json'), 'exit': exit_code, 'tests_run': receipt['tests_run']}))
    return exit_code


if __name__ == '__main__':
    sys.exit(main())

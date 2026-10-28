#!/usr/bin/env python3
"""Offline, retained-evidence runner for the bounded reference-path change.

Guards are process-local defense in depth, not a hostile-code sandbox. This file
is never imported by discovery. No network, subprocess or broad test discovery.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import traceback
import unittest
import uuid

sys.dont_write_bytecode = True
BASE = 'a1f648632e64561d82dcbeb20d9bda19f812560a'
BASE_RESTORE = '17dc0aadacd0411d9bddac7689cb7fbaf0a8fc469e5531188f5682452a41a109'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def head_of(repo):
    git = repo / '.git'
    require(git.is_dir(), 'Expected standalone operator-staged repository')
    head = (git / 'HEAD').read_text().strip()
    if head.startswith('ref: '):
        ref = head[5:]
        require(ref.startswith('refs/') and '..' not in Path(ref).parts, 'Unsafe git ref')
        direct = git / ref
        if direct.is_file():
            head = direct.read_text().strip()
        else:
            rows = (git / 'packed-refs').read_text().splitlines()
            head = next(row.split()[0] for row in rows if row.endswith(' ' + ref))
    require(re.fullmatch('[0-9a-f]{40}', head) is not None, 'Invalid HEAD')
    return head


def source_hashes(repo):
    paths = [repo / 'src/skippercast/seafloor/restore.py',
             repo / 'tests/unit/test_sc8c_restore_paths.py', Path(__file__).resolve()]
    paths.extend(sorted((repo / 'tests/fixtures/sc8c-restore-paths').rglob('*')))
    return {str(path.relative_to(repo)): file_hash(path) for path in paths if path.is_file()}


def forbidden_event(event):
    return (event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn', 'pty.'))
            or event in {'os.system', 'os.fork', 'os.forkpty', 'ctypes.dlopen'})


class InertDenied(Exception):
    pass


class Guards:
    def __init__(self, repo, run):
        self.run = run.resolve()
        self.read_roots = [self.run, (repo / 'src').resolve(),
                           (repo / 'tests/unit/__pycache__').resolve(),
                           (repo / 'tests/fixtures/sc8c-restore-paths').resolve(),
                           Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()]
        self.read_files = {Path(__file__).resolve(),
                           (repo / 'tests/unit/test_sc8c_restore_paths.py').resolve(),
                           (repo / 'tests/fixtures/sc8c-restore-paths/seed.json').resolve()}
        self.violations = []

    def allowed(self, path, write=False):
        if isinstance(path, int):
            return False  # No fixture descriptor escapes are needed by this runner.
        path = Path(os.fsdecode(path)).resolve()
        if write:
            return path.is_relative_to(self.run)
        return path in self.read_files or any(path.is_relative_to(root) for root in self.read_roots)

    def __call__(self, event, args):
        # An inert event exercises the very same path classifier without issuing
        # any forbidden file/network/child operation. Expected only here.
        if event == 'sc8c.inert-path-probe':
            if not self.allowed(args[0], write=True):
                raise InertDenied('inert denied path')
            return
        reason = None
        if forbidden_event(event):
            reason = event
        elif event == 'open':
            path, mode, flags = args
            write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not self.allowed(path, write):
                reason = 'open outside admitted ' + ('write' if write else 'read') + ' roots'
        elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate', 'os.mkfifo'}:
            if not self.allowed(args[0], write=True):
                reason = event + ' outside run'
        elif event in {'os.rename', 'os.link'}:
            if not all(self.allowed(path, write=True) for path in args[:2]):
                reason = event + ' outside run'
        elif event == 'os.symlink':
            if not all(self.allowed(path, write=True) for path in args[:2]):
                reason = 'symlink outside run'
        elif event in {'os.listdir', 'os.scandir'}:
            if not self.allowed(args[0]):
                reason = event + ' outside read roots'
        if reason:
            self.violations.append({'event': event, 'reason': reason})
            raise PermissionError('SC8C GUARD STOP: ' + reason)


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append({'test_id': test.id(), 'outcome': 'passed'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({'test_id': test.id(), 'outcome': 'failed'})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({'test_id': test.id(), 'outcome': 'error'})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append({'test_id': test.id(), 'outcome': 'skipped', 'reason': reason})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True,
                        choices=['baseline', 'regression', 'compatibility', 'negative-control'])
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    manifest_path = args.source_manifest.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text())
    write_root = manifest_path.parent
    require(manifest.get('schema') == 'agentorange.source-manifest/v1', 'Manifest schema mismatch')
    require(Path(manifest['write_root']).resolve(strict=True) == write_root, 'write_root mismatch')
    require(Path(manifest['repo']).resolve(strict=True) == repo == write_root / 'repo', 'repo binding mismatch')
    require(manifest['head'] == BASE and manifest['clean'] is True, 'Admitted base/clean mismatch')
    runtime = manifest['runtime']
    require((repo / '.venv').is_symlink(), 'Expected admitted linked runtime')
    require((repo / '.venv').resolve(strict=True) == Path(runtime['repo_venv']).resolve(strict=True),
            'Runtime link mismatch (operator disposition admits shared venv)')
    require(Path(sys.prefix).resolve() == (repo / '.venv').resolve(), 'Wrong interpreter prefix')
    scan_python = write_root.parent.parent / 'tools/venv-fullsuite/bin/python3'
    require(runtime['credential_scan_python3'] == str(scan_python), 'Scan interpreter mismatch')
    out = args.out.resolve()
    require(out.is_relative_to(write_root) and not out.is_relative_to(repo), 'Output must be in candidate, outside repo')
    out.mkdir(parents=True, exist_ok=True)
    run = out / uuid.uuid4().hex
    run.mkdir(exist_ok=False)
    synthetic = run / 'synthetic'
    synthetic.mkdir()
    head = head_of(repo)
    before = source_hashes(repo)
    if args.suite == 'baseline':
        require(head == BASE and before['src/skippercast/seafloor/restore.py'] == BASE_RESTORE,
                'Baseline must call the exact real pinned function')
    receipt = {'schema': 'skippercast.sc8c-run/v1', 'suite': args.suite, 'argv': sys.argv,
               'cwd': str(Path.cwd()), 'interpreter': sys.executable, 'head': head,
               'admitted_base': BASE, 'source_manifest_sha256': file_hash(manifest_path),
               'source_fixture_hashes_before': before, 'run_root': str(run),
               'tests': [], 'preservation': [], 'isolation': [], 'exit': 1}
    guards = Guards(repo, run)
    sys.addaudithook(guards)
    # Guards precede any product/test import. No hooks are installed by the test
    # module, so ordinary peer test discovery is unaffected.
    sys.path.insert(0, str(repo / 'src'))
    tempfile.tempdir = str(synthetic)
    stdout_path, stderr_path = run / 'stdout.txt', run / 'stderr.txt'
    with stdout_path.open('w') as stdout, stderr_path.open('w') as stderr, \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            isolation = receipt['isolation']
            def checked(name, condition):
                require(condition, name)
                isolation.append({'test_id': name, 'outcome': 'passed'})
            checked('candidate-root-binding', repo == write_root / 'repo')
            checked('unique-output-root', run.parent == out and run.is_dir())
            checked('pre-import-no-network-no-child', all(forbidden_event(event) for event in
                    ('socket.connect', 'subprocess.Popen', 'os.fork', 'os.system', 'os.posix_spawn', 'pty.spawn')))
            sys.audit('sc8c.inert-path-probe', str(synthetic / 'allowed.txt'))
            checked('allowed-synthetic-path', guards.allowed(synthetic / 'allowed.txt', write=True))
            try:
                sys.audit('sc8c.inert-path-probe', str(repo / 'inert-denied-not-opened'))
            except InertDenied:
                checked('inert-denied-sentinel-event', True)
            else:
                raise RuntimeError('Inert denied path was accepted')
            import skippercast.paths as paths
            paths.repo_root = lambda: synthetic
            import skippercast.platform.contracts as contracts
            from skippercast.seafloor import restore
            checked('pre-contract-root-redirection', contracts.REPO == synthetic and
                    (restore.restore_reference.__kwdefaults__ or {}).get('root') == synthetic)
            spec = importlib.util.spec_from_file_location('sc8c_restore_tests',
                                                          repo / 'tests/unit/test_sc8c_restore_paths.py')
            if spec is None or spec.loader is None:
                raise RuntimeError('Cannot load the admitted direct test module')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.RestorePaths.workspace = synthetic
            module.RestorePaths.evidence = receipt['preservation']
            all_names = unittest.defaultTestLoader.getTestCaseNames(module.RestorePaths)
            if args.suite == 'baseline':
                names = ['test_reject_symlink_root_var']
            elif args.suite == 'negative-control':
                names = ['test_mutant_preflight_disabled']
            elif args.suite == 'compatibility':
                names = [name for name in all_names if name.startswith(('test_mismatch_',)) or name in {
                    'test_fresh_destination', 'test_existing_destination', 'test_unrelated_venv_link',
                    'test_unresolved_ancestor_aliases', 'test_root_alias', 'test_staged_alias', 'test_both_aliases'}]
            else:
                names = [name for name in all_names if name != 'test_mutant_preflight_disabled']
            tests = [module.RestorePaths(name) for name in names]
            result = unittest.TextTestRunner(stream=stderr, verbosity=2, failfast=True,
                                             resultclass=Results).run(unittest.TestSuite(tests))
            receipt.update(tests=result.rows, tests_run=result.testsRun,
                           failures=len(result.failures), errors=len(result.errors), skips=len(result.skipped))
            require(result.testsRun == len(names) and not result.skipped, 'Missing/skipped required tests')
            checked('all-fixture-io-in-synthetic-tree', not guards.violations)
            after = source_hashes(repo)
            receipt['source_fixture_hashes_after'] = after
            checked('unchanged-authored-fixture-and-source-bytes', after == before)
            if args.suite == 'negative-control':
                receipt['mutant_detected'] = getattr(tests[0], 'mutant_detected', False)
                receipt['positive_passed'] = getattr(tests[0], 'positive_passed', False)
                require(receipt['mutant_detected'] and receipt['positive_passed'], 'Mutation control incomplete')
            require(result.wasSuccessful(), 'Required test failure; see raw stderr')
            receipt['exit'] = 0
            print(json.dumps({'suite': args.suite, 'tests_run': result.testsRun,
                              'isolation_assertions': len(isolation), 'exit': 0}))
        except Exception:
            traceback.print_exc()
    receipt['guard_violations'] = guards.violations
    receipt['stdout_sha256'] = file_hash(stdout_path)
    receipt['stderr_sha256'] = file_hash(stderr_path)
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(run / 'receipt.json'), 'exit': receipt['exit'],
                      'tests_run': receipt.get('tests_run', 0)}))
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())

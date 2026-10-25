"""Offline SC172 acceptance runner and reversible test support.

Exercises the real reviewed_receipt/source_files APIs of the candidate's
seafloor multibeam adapter on synthetic, card-created receipts and paired cache
bytes only: no ingest, raster processing, source operation, acquisition,
network, model call or child execution. The runner derives its repository from
this file, suppresses bytecode and puts the candidate src/ first on sys.path
itself; no environment override is needed.
"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import argparse
import builtins
import hashlib
import importlib
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

REPO = Path(__file__).resolve().parents[1]
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
CONTRACT = 'SC172-PREPARATION-JSON/v1'
TEST_FILE = REPO / 'tests/unit/test_sc172_preparation_json.py'
FIXTURE = REPO / 'tests/fixtures/sc172-preparation-json'
TEST_CLASS = 'PreparationReceiptJsonTests'
PEERS = ('APeerBeforeTests', 'ZPeerAfterTests')
METHODS = ['test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation']
# Frozen subcase counts per method; a missing or extra subcase fails acceptance.
EXPECTED_CASES = {'test_regression': 47, 'test_compatibility': 27,
                  'test_negative_control': 27, 'test_preservation': 15}
GUARDED = ('socket.create_connection', 'socket.getaddrinfo', 'socket.socket.connect',
           'socket.socket.connect_ex', 'socket.socket.sendto', 'subprocess.Popen', 'os.system',
           'os.popen', 'os.execv', 'os.execve', 'os.execl', 'os.execlp', 'os.execvp',
           'os.execvpe', 'os.spawnv', 'os.spawnve', 'os.spawnvp', 'os.spawnvpe', 'os.fork',
           'os.posix_spawn', 'os.posix_spawnp')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def fixture_hashes():
    return {str(p.relative_to(REPO)): digest(p) for p in sorted(FIXTURE.rglob('*')) if p.is_file()}


def log_inventory(root, names):
    result = {}
    for name in names:
        path = Path(root) / name
        if not path.is_file():
            raise ValueError('missing evidence log: ' + name)
        data = path.read_bytes()
        result[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                        'newlines': data.count(b'\n')}
    return result


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm',
                                     'hermes_tools', 'transformers'}:
            raise RuntimeError('offline model import refused')
        return None


def _owner(module):
    return socket.socket if module == 'socket.socket' else importlib.import_module(module)


class OfflineProduct:
    """Fixture-scoped, reversible seams installed before any product import.

    Refuses network, model imports and child execution; confines Python-level
    writes to `allowed`; redirects skippercast.paths.repo_root to synthetic
    state before any product import. An accidental-side-effect guard, not a
    hostile-code sandbox; no audit hooks or fake dependency modules.
    """
    PREFIXES = ('skippercast',)

    def __init__(self, allowed):
        self.allowed = Path(allowed).resolve()
        self.synthetic_root = self.allowed / 'synthetic-repo-root'
        self.stack = ExitStack()
        self.events = []

    def refuse(self, *args, **kwargs):
        self.events.append('refused-side-effect')
        raise RuntimeError('offline network/model/child execution refused')

    def _ours(self, name):
        return any(name == p or name.startswith(p + '.') for p in self.PREFIXES)

    def __enter__(self):
        self.old_path = sys.path[:]
        self.old_meta = sys.meta_path[:]
        self.old_bytecode = sys.dont_write_bytecode
        self.old_modules = {k: v for k, v in sys.modules.items() if self._ours(k)}
        for key in self.old_modules:
            sys.modules.pop(key)
        sys.path.insert(0, str(REPO / 'src'))
        sys.dont_write_bytecode = True
        sys.meta_path.insert(0, NoModels())
        try:
            for target in GUARDED:
                module, name = target.rsplit('.', 1)
                owner = _owner(module)
                if hasattr(owner, name):
                    self.stack.enter_context(patch.object(owner, name, self.refuse))
            for owner, name in ((builtins, 'open'), (io, 'open')):
                original = getattr(owner, name)

                def guarded(file, mode='r', *args, _open=original, **kwargs):
                    if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in 'wax+'):
                        path = Path(os.fsdecode(file)).absolute()
                        if not (path.is_relative_to(self.allowed) or str(path) == os.devnull):
                            self.events.append('refused-write')
                            raise RuntimeError('offline write outside admitted root refused')
                    return _open(file, mode, *args, **kwargs)
                self.stack.enter_context(patch.object(owner, name, guarded))
            paths = importlib.import_module('skippercast.paths')
            self.stack.enter_context(patch.object(paths, 'repo_root', return_value=self.synthetic_root))
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def origins(self):
        """Every loaded product module must resolve to this candidate's src/."""
        found = {}
        for name, module in sorted(sys.modules.items()):
            if self._ours(name):
                origin = getattr(module, '__file__', None)
                if origin:
                    resolved = Path(origin).resolve()
                    if not resolved.is_relative_to(REPO / 'src'):
                        raise RuntimeError('product imported outside candidate: ' + name)
                    found[name] = str(resolved)
        contracts = sys.modules.get('skippercast.platform.contracts')
        if contracts is not None and Path(contracts.REPO) != self.synthetic_root:
            raise RuntimeError('platform.contracts REPO not redirected to synthetic state')
        return found

    def __exit__(self, *exc):
        self.stack.close()
        for key in list(sys.modules):
            if self._ours(key):
                sys.modules.pop(key)
        sys.modules.update(self.old_modules)
        sys.path[:] = self.old_path
        sys.meta_path[:] = self.old_meta
        sys.dont_write_bytecode = self.old_bytecode
        return False


def peer_state():
    """A harmless peer observation; must be identical before and after the suite."""
    tracked = {}
    for target in GUARDED + ('builtins.open', 'io.open', 'json.loads', 'json.dumps'):
        module, name = target.rsplit('.', 1)
        owner = _owner(module)
        tracked[target] = id(getattr(owner, name, None))
    return {'sys.path': list(sys.path), 'meta_path': [type(f).__name__ for f in sys.meta_path],
            'product_modules': sorted(k for k in sys.modules if k == 'skippercast' or k.startswith('skippercast.')),
            'environ_sha256': hashlib.sha256(json.dumps(sorted(os.environ.items())).encode()).hexdigest(),
            'cwd': os.getcwd(), 'dont_write_bytecode': sys.dont_write_bytecode, 'callables': tracked}


def validate_manifest(path):
    data = json.loads(Path(path).read_text())
    runtime = data.get('runtime', {})
    scan = Path(runtime.get('credential_scan_python3', ''))
    if (data.get('schema') != 'agentorange.source-manifest/v1'
            or data.get('head') != BASE
            or Path(data.get('repo', '')).resolve() != REPO
            or Path(data.get('write_root', '')).resolve() != REPO.parent
            or Path(runtime.get('repo_venv', '')).resolve() != (REPO / '.venv').resolve()
            or not scan.is_absolute() or not scan.is_file()):
        raise ValueError('staging manifest mismatch; existing staging owner required')
    return data


def git(*args):
    result = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []

    def startTest(self, test):
        super().startTest(test)
        self.ids.append(test.id())


def load_tests_module():
    spec = importlib.util.spec_from_file_location('test_sc172_preparation_json', TEST_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError('missing SC172 test module')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.out.resolve().is_relative_to(REPO.parent / 'out'):
        parser.error('--out must be beneath the candidate sibling out area')
    manifest = validate_manifest(args.source_manifest)
    spec = REPO.parent / 'ACCEPTANCE-SPEC.json'
    if not spec.is_file():
        parser.error('frozen ACCEPTANCE-SPEC.json missing beside repo; existing staging owner required')
    # Read-only git identity before any product import; never product execution.
    head = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain', '--untracked-files=normal')
    root = args.out.resolve() / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    peer_before = peer_state()
    module = load_tests_module()
    test_class = getattr(module, TEST_CLASS)
    test_class.OUTPUT_ROOT = root
    suite = unittest.TestSuite()
    suite.addTest(getattr(module, PEERS[0])('test_peer'))
    suite.addTests(test_class(name) for name in METHODS)
    suite.addTest(getattr(module, PEERS[1])('test_peer'))
    with (root / 'stdout.txt').open('w') as stdout, (root / 'stderr.txt').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = unittest.TextTestRunner(stream=stderr, verbosity=2,
                                            resultclass=RecordingResult).run(suite)
    peer_after = peer_state()
    details_path = root / 'test-details.json'
    details = json.loads(details_path.read_text()) if details_path.is_file() else {}
    expected_ids = (['test_sc172_preparation_json.%s.test_peer' % PEERS[0]]
                    + ['test_sc172_preparation_json.%s.%s' % (TEST_CLASS, name) for name in METHODS]
                    + ['test_sc172_preparation_json.%s.test_peer' % PEERS[1]])
    cases = details.get('cases', {})
    counts = {name: len(cases.get(name, [])) for name in METHODS}
    unique = {name: len(set(cases.get(name, []))) for name in METHODS}
    control = details.get('negative_control', {})
    checks = {
        'details_written': bool(details),
        'unittest_successful': result.wasSuccessful(),
        'no_skips': not result.skipped,
        'all_methods_ran': result.testsRun == len(expected_ids) and result.ids == expected_ids,
        'subcase_counts': counts == EXPECTED_CASES and unique == EXPECTED_CASES,
        'negative_control_detected': bool(control.get('detected'))
        and control.get('detected') == control.get('expected'),
        'negative_control_restored': control.get('restored') is True,
        'guard_events_empty': details.get('guard_events') == [],
        'peer_state_unchanged': peer_before == peer_after,
    }
    successful = all(checks.values())
    log_names = ['stdout.txt', 'stderr.txt', 'test-details.json']
    receipt = {'schema': 'sc172.acceptance/v1', 'contract': CONTRACT,
               'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
               'interpreter': sys.executable, 'base': BASE, 'head': head,
               'tracked_and_untracked_status': status,
               'source_manifest_sha256': digest(args.source_manifest),
               'source_manifest_head': manifest.get('head'),
               'spec_sha256': digest(spec), 'inputs': fixture_hashes(),
               'module_origins': details.get('module_origins'), 'executed_ids': result.ids,
               'test_count': result.testsRun, 'case_counts': counts,
               'expected_case_counts': EXPECTED_CASES,
               'negative_control': control, 'peer_state_unchanged': peer_before == peer_after,
               'skips': len(result.skipped), 'failures': len(result.failures),
               'errors': len(result.errors), 'checks': checks,
               'exit': 0 if successful else 1}
    if not details_path.is_file():
        log_names.remove('test-details.json')
    # Seal only after every writer (unittest, details) has finished.
    receipt['logs'] = log_inventory(root, log_names)
    receipt['result_file'] = 'result.json'
    finalize(root, receipt, log_names)
    print(json.dumps({'result': str(root / 'result.json'), 'tests': result.testsRun, 'cases': counts,
                      'failures': len(result.failures), 'errors': len(result.errors),
                      'skips': len(result.skipped), 'checks': checks,
                      'exit': receipt['exit']}, sort_keys=True))
    return receipt['exit']


RESULT_NAMES = ('result.json', 'receipt.json')


def finalize(root, receipt, log_names):
    """Write result.json (required) plus the receipt.json alias, then verify.

    Any late log mutation or a missing/unequal result file forces exit 1 and is
    recorded truthfully in the final result.
    """
    for name in RESULT_NAMES:
        dump(root / name, receipt)
    problems = []
    if log_inventory(root, log_names) != receipt['logs']:
        problems.append('late_log_mutation')
    for name in RESULT_NAMES:
        path = root / name
        if not path.is_file() or json.loads(path.read_text()) != receipt:
            problems.append('result_file_invalid:' + name)
    if problems:
        receipt.update(exit=1, finalize_problems=problems)
        for name in RESULT_NAMES:
            dump(root / name, receipt)
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())

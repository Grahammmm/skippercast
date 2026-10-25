"""Offline SC161 acceptance runner and reversible test support.

Pure metadata predicate only: no prepare, Store, reservation, native startup,
source operation, acquisition, network, model call or child execution. The
runner derives its repository from this file, suppresses bytecode and puts the
candidate src/ first on sys.path itself; no environment override is needed.
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
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
CONTRACT = 'SC161-PACKET-INTEGERS/v1'
TEST_FILE = REPO / 'tests/unit/test_sc161_packet_integers.py'
FIXTURE = REPO / 'tests/fixtures/sc161-packet-integers'
TEST_CLASS = 'PacketIntegerBindingTests'
METHODS = ['test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation']
# Frozen subcase counts per method; a missing or extra subcase fails acceptance.
EXPECTED_CASES = {'test_regression': 69, 'test_compatibility': 15,
                  'test_negative_control': 21, 'test_preservation': 12}
ORIGINAL_SELECTORS = [
    'tests/unit/test_coastal_partial_support.py::test_strict_policy_and_grant_identity_digests_are_unchanged',
    'tests/unit/test_coastal_partial_support.py::test_partial_grant_identity_binds_support_policy_and_packets',
]
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
    for target in GUARDED + ('builtins.open', 'io.open'):
        module, name = target.rsplit('.', 1)
        owner = _owner(module)
        tracked[target] = id(getattr(owner, name, None))
    return {'sys.path': list(sys.path), 'meta_path': [type(f).__name__ for f in sys.meta_path],
            'product_modules': sorted(k for k in sys.modules if k == 'skippercast' or k.startswith('skippercast.')),
            'environ_sha256': hashlib.sha256(json.dumps(sorted(os.environ.items())).encode()).hexdigest(),
            'dont_write_bytecode': sys.dont_write_bytecode, 'callables': tracked}


def validate_manifest(path):
    data = json.loads(Path(path).read_text())
    runtime = data.get('runtime', {})
    if (data.get('schema') != 'agentorange.source-manifest/v1'
            or data.get('head') != BASE
            or Path(data.get('repo', '')).resolve() != REPO
            or Path(data.get('write_root', '')).resolve() != REPO.parent
            or Path(runtime.get('repo_venv', '')).resolve() != (REPO / '.venv').resolve()):
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
    spec = importlib.util.spec_from_file_location('test_sc161_packet_integers', TEST_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError('missing SC161 test module')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SelectorCollector:
    def __init__(self):
        self.collected = []
        self.reports = []

    def pytest_collection_modifyitems(self, session, config, items):
        self.collected = [item.nodeid for item in items]

    def pytest_runtest_logreport(self, report):
        self.reports.append({'nodeid': report.nodeid, 'when': report.when, 'outcome': report.outcome})


def run_original_selectors(root):
    """Compatibility phase: the two listed original selectors via the installed pytest API."""
    import pytest
    basetemp = root / 'pytest-basetemp'
    collector = SelectorCollector()
    env_before = dict(os.environ)
    path_before = sys.path[:]
    other_before = {k for k in sys.modules if k == 'tests' or k.startswith('tests.')
                    or k in ('conftest', 'test_coastal_partial_support')}
    argv = ['-p', 'no:cacheprovider', '--basetemp', str(basetemp), '--capture=sys',
            '--rootdir', str(REPO), '-c', str(REPO / 'pyproject.toml'), '-q', '-rA',
            *[str(REPO / s.split('::')[0]) + '::' + s.split('::')[1] for s in ORIGINAL_SELECTORS]]
    guard = OfflineProduct(root)
    with (root / 'pytest-stdout.txt').open('w') as out, (root / 'pytest-stderr.txt').open('w') as err:
        with redirect_stdout(out), redirect_stderr(err):
            with guard:
                code = int(pytest.main(argv, plugins=[collector]))
                origins = guard.origins()
    # Restore conftest's environment default and pytest's path/module additions.
    for key in set(os.environ) - set(env_before):
        del os.environ[key]
    os.environ.update(env_before)
    sys.path[:] = path_before
    for key in list(sys.modules):
        if ((key == 'tests' or key.startswith('tests.') or key in ('conftest', 'test_coastal_partial_support'))
                and key not in other_before):
            sys.modules.pop(key)
    expected = list(ORIGINAL_SELECTORS)
    calls = {r['nodeid']: r['outcome'] for r in collector.reports if r['when'] == 'call'}
    skipped = [r for r in collector.reports if r['outcome'] == 'skipped']
    ok = (code == 0 and collector.collected == expected and not skipped
          and calls == {s: 'passed' for s in expected} and not guard.events)
    return {'argv': argv, 'exit': code, 'collected': collector.collected, 'expected': expected,
            'call_outcomes': calls, 'skips': len(skipped), 'guard_events': guard.events,
            'module_origins': origins, 'basetemp': str(basetemp), 'passed': ok}


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.out.resolve().is_relative_to(REPO.parent / 'out'):
        parser.error('--out must be beneath the candidate sibling out area')
    validate_manifest(args.source_manifest)
    spec = REPO.parent / 'SPEC.json'
    if not spec.is_file():
        parser.error('frozen SPEC.json missing beside repo; existing staging owner required')
    # Read-only git identity before any product import; never product execution.
    head = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain', '--untracked-files=normal')
    root = args.out.resolve() / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    peer_before = peer_state()
    module = load_tests_module()
    test_class = getattr(module, TEST_CLASS)
    test_class.OUTPUT_ROOT = root
    suite = unittest.TestSuite(test_class(name) for name in METHODS)
    with (root / 'stdout.txt').open('w') as stdout, (root / 'stderr.txt').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = unittest.TextTestRunner(stream=stderr, verbosity=2,
                                            resultclass=RecordingResult).run(suite)
    selectors = run_original_selectors(root)
    peer_after = peer_state()
    details = json.loads((root / 'test-details.json').read_text())
    expected_ids = ['test_sc161_packet_integers.%s.%s' % (TEST_CLASS, name) for name in METHODS]
    counts = {name: len(details['cases'].get(name, [])) for name in METHODS}
    unique = {name: len(set(details['cases'].get(name, []))) for name in METHODS}
    checks = {
        'unittest_successful': result.wasSuccessful(),
        'no_skips': not result.skipped,
        'all_methods_ran': result.testsRun == len(METHODS) and result.ids == expected_ids,
        'subcase_counts': counts == EXPECTED_CASES and unique == EXPECTED_CASES,
        'negative_control_detected': details.get('negative_control', {}).get('detected') == details.get(
            'negative_control', {}).get('expected') and bool(details.get('negative_control', {}).get('detected')),
        'negative_control_restored': details.get('negative_control', {}).get('restored') is True,
        'original_selectors': selectors['passed'],
        'peer_state_unchanged': peer_before == peer_after,
    }
    successful = all(checks.values())
    log_names = ['stdout.txt', 'stderr.txt', 'pytest-stdout.txt', 'pytest-stderr.txt', 'test-details.json']
    receipt = {'schema': 'sc161.acceptance/v1', 'contract': CONTRACT,
               'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
               'interpreter': sys.executable, 'base': BASE, 'head': head,
               'tracked_and_untracked_status': status,
               'source_manifest_sha256': digest(args.source_manifest),
               'spec_sha256': digest(spec), 'inputs': fixture_hashes(),
               'module_origins': details['module_origins'], 'executed_ids': result.ids,
               'test_count': result.testsRun, 'case_counts': counts,
               'expected_case_counts': EXPECTED_CASES,
               'negative_control': details.get('negative_control'),
               'original_selectors': selectors, 'peer_state_unchanged': peer_before == peer_after,
               'skips': len(result.skipped), 'failures': len(result.failures),
               'errors': len(result.errors), 'checks': checks,
               'exit': 0 if successful else 1}
    # Seal only after every writer (unittest, pytest, details) has finished.
    receipt['logs'] = log_inventory(root, log_names)
    dump(root / 'receipt.json', receipt)
    if log_inventory(root, log_names) != receipt['logs']:
        receipt.update(exit=1, late_log_mutation=True)
        dump(root / 'receipt.json', receipt)
    print(json.dumps({'receipt': str(root / 'receipt.json'), 'tests': result.testsRun,
                      'cases': counts, 'failures': len(result.failures),
                      'errors': len(result.errors), 'selectors': selectors['passed'],
                      'checks': checks, 'exit': receipt['exit']}, sort_keys=True))
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())

"""Offline SC159 acceptance runner and reversible test support.

No acquisition or native source startup is permitted. Genuine GIS imports are
qualified here; the test getter serves only card-owned synthetic bytes.
"""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
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
import tempfile
import unittest
from unittest.mock import patch
import uuid

REPO = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
CONTRACT = 'SC159-TITLE33-METADATA/v1'
METHODS = {
    'regression': ['test_positive_contract', 'test_rejects_malformed'],
    'compatibility': ['test_baseline_compatibility', 'test_isolation_and_discovery'],
    'negative-control': ['test_deciding_negative_control'],
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def log_inventory(root):
    root = Path(root)
    result = {}
    for name in ('stdout.txt', 'stderr.txt'):
        path = root / name
        if not path.is_file():
            raise ValueError('missing evidence log: ' + name)
        data = path.read_bytes()
        result[name] = {'sha256': hashlib.sha256(data).hexdigest(),
                        'bytes': len(data), 'newlines': data.count(b'\n')}
    return result


def verify_logs(root, expected):
    if log_inventory(root) != expected:
        raise ValueError('changed evidence log')
    return True


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm',
                                     'hermes_tools', 'transformers'}:
            raise RuntimeError('offline model import refused')
        return None


class OfflineProduct:
    """Fixture-scoped seams, installed before any product import.

    This is an accidental-side-effect guard, not a hostile-code sandbox. No
    permanent audit hooks or fake native libraries are installed. Native library
    data lookups needed for ordinary imports remain genuine staged dependencies.
    """
    def __init__(self, state):
        self.state = Path(state).resolve()
        self.stack = ExitStack()
        self.origins = {}
        self.events = []

    def refuse(self, *args, **kwargs):
        self.events.append('refused-side-effect')
        raise RuntimeError('offline network/model/child execution refused')

    def __enter__(self):
        self.old_path = sys.path[:]
        self.old_meta = sys.meta_path[:]
        self.old_bytecode = sys.dont_write_bytecode
        self.old_modules = {k: v for k, v in sys.modules.items()
                            if k == 'skippercast' or k.startswith('skippercast.')}
        for key in self.old_modules:
            sys.modules.pop(key)
        sys.path.insert(0, str(REPO / 'src'))
        sys.dont_write_bytecode = True
        sys.meta_path.insert(0, NoModels())
        try:
            for target in ('socket.create_connection', 'socket.getaddrinfo',
                           'socket.socket.connect', 'socket.socket.connect_ex',
                           'socket.socket.sendto', 'subprocess.Popen', 'os.system',
                           'os.popen', 'os.execv', 'os.execve', 'os.execl',
                           'os.execlp', 'os.execvp', 'os.execvpe', 'os.spawnv',
                           'os.spawnve', 'os.spawnvp', 'os.spawnvpe', 'os.fork',
                           'os.posix_spawn', 'os.posix_spawnp'):
                module, name = target.rsplit('.', 1)
                owner = importlib.import_module(module) if module != 'socket.socket' else socket.socket
                if hasattr(owner, name):
                    self.stack.enter_context(patch.object(owner, name, self.refuse))
            # Refuse Python-level host/catalog/cache reads during product imports.
            # Reads of source bytes, genuine installed packages and synthetic state
            # are allowed. Writes are confined to the test's own state.
            for owner, name in ((builtins, 'open'), (io, 'open')):
                original = getattr(owner, name)
                def guarded(file, mode='r', *args, _open=original, **kwargs):
                    if isinstance(file, (str, bytes, os.PathLike)):
                        path = Path(os.fsdecode(file)).absolute()
                        write = any(ch in mode for ch in 'wax+')
                        if write and not path.is_relative_to(self.state):
                            raise RuntimeError('offline write outside synthetic state')
                        allowed = (path.is_relative_to(self.state)
                                   or path.is_relative_to(REPO / 'src')
                                   or path.is_relative_to(REPO / 'tests')
                                   or path.is_relative_to(REPO / 'tools')
                                   or path.is_relative_to(Path(sys.prefix))
                                   or path.is_relative_to(Path(sys.base_prefix))
                                   or str(path) in {'/dev/null', '/proc/meminfo'})
                        if not allowed:
                            raise RuntimeError('offline host/source read refused')
                    return _open(file, mode, *args, **kwargs)
                self.stack.enter_context(patch.object(owner, name, guarded))
            paths = importlib.import_module('skippercast.paths')
            self.stack.enter_context(patch.object(paths, 'repo_root', return_value=self.state))
            http = importlib.import_module('skippercast.http')
            self.stack.enter_context(patch.object(http, 'default_session', self.refuse))
            self.stack.enter_context(patch.object(http.Session, 'get', self.refuse))
            self.stack.enter_context(patch.object(http.Session, 'download', self.refuse))
            self.product = importlib.import_module('skippercast.seafloor.screen_sources')
            contracts = importlib.import_module('skippercast.platform.contracts')
            if contracts.REPO != self.state or self.product.refresh.__defaults__[0] != self.state:
                raise RuntimeError('synthetic root/default redirection failed')
            for name, module in list(sys.modules.items()):
                if name == 'skippercast' or name.startswith('skippercast.'):
                    origin = getattr(module, '__file__', None)
                    if origin:
                        if not Path(origin).resolve().is_relative_to(REPO / 'src'):
                            raise RuntimeError('product imported outside candidate')
                        self.origins[name] = str(Path(origin).resolve())
            for name in ('pyproj', 'shapely', 'rasterio', 'numpy'):
                module = importlib.import_module(name)
                self.origins[name] = str(Path(module.__file__).resolve())
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *exc):
        self.stack.close()
        for key in list(sys.modules):
            if key == 'skippercast' or key.startswith('skippercast.'):
                sys.modules.pop(key)
        sys.modules.update(self.old_modules)
        sys.path[:] = self.old_path
        sys.meta_path[:] = self.old_meta
        sys.dont_write_bytecode = self.old_bytecode


def validate_manifest(path):
    data = json.loads(Path(path).read_text())
    if (data.get('schema') != 'agentorange.source-manifest/v1'
            or data.get('head') != BASE
            or Path(data.get('repo', '')).resolve() != REPO
            or Path(data.get('write_root', '')).resolve() != REPO.parent
            or Path(data.get('runtime', {}).get('repo_venv', '')).resolve()
            != (REPO / '.venv').resolve()):
        raise ValueError('staging manifest mismatch; existing staging owner required')
    return data


def git(*args):
    result = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


class RecordingResult(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.ids.append(test.id())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []


def load_tests_module():
    # The test module imports ROOT from tests._support, as pytest's
    # `pythonpath = ["."]` allows; give this direct runner the same root.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    path = REPO / 'tests/gis/test_sc159_title33_metadata.py'
    spec = importlib.util.spec_from_file_location('test_sc159_title33_metadata', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=METHODS, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    validate_manifest(args.source_manifest)
    head = git('rev-parse', 'HEAD')
    # Record identity before guards: these are read-only git discovery children,
    # never product execution. Product imports occur only inside OfflineProduct.
    status = git('status', '--porcelain', '--untracked-files=normal')
    if not args.out.resolve().is_relative_to(REPO.parent / 'out'):
        parser.error('--out must be beneath candidate sibling out')
    root = args.out / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    module = load_tests_module()
    module.Title33MetadataTests.OUTPUT_ROOT = root
    suite = unittest.TestSuite(module.Title33MetadataTests(name) for name in METHODS[args.suite])
    with (root / 'stdout.txt').open('w') as stdout, (root / 'stderr.txt').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = unittest.TextTestRunner(stream=stderr, verbosity=2,
                                            resultclass=RecordingResult).run(suite)
    successful = (result.wasSuccessful() and not result.skipped
                  and result.testsRun == len(METHODS[args.suite])
                  and len(result.ids) == len(METHODS[args.suite]))
    details = json.loads((root / 'test-details.json').read_text())
    required_cases = {'regression': 63, 'compatibility': 13, 'negative-control': 3}
    expected_ids = {'test_sc159_title33_metadata.Title33MetadataTests.' + name
                    for name in METHODS[args.suite]}
    successful = (successful and set(result.ids) == expected_ids
                  and len(details['case_ids']) == required_cases[args.suite]
                  and len(set(details['case_ids'])) == required_cases[args.suite])
    receipt = {'schema': 'sc159.acceptance/v1', 'contract': CONTRACT,
               'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
               'interpreter': sys.executable, 'base': BASE, 'head': head,
               'tracked_and_untracked_status': status,
               'source_manifest_sha256': digest(args.source_manifest),
               'spec_sha256': digest(REPO.parent / 'SPEC.json'),
               'inputs': {str(p.relative_to(REPO)): digest(p) for p in
                          sorted((REPO / 'tests/fixtures/sc159-title33-metadata').rglob('*')) if p.is_file()},
               'module_origins': details['module_origins'], 'executed_ids': result.ids,
               'test_count': result.testsRun, 'case_ids': details['case_ids'],
               'case_count': len(details['case_ids']), 'skips': len(result.skipped),
               'failures': len(result.failures), 'errors': len(result.errors),
               'exit': 0 if successful else 1, 'logs': log_inventory(root)}
    dump(root / 'receipt.json', receipt)
    verify_logs(root, receipt['logs'])
    print(json.dumps({'receipt': str(root / 'receipt.json'),
                      'tests': result.testsRun, 'cases': len(details['case_ids']),
                      'failures': len(result.failures), 'errors': len(result.errors),
                      'exit': receipt['exit']}))
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())

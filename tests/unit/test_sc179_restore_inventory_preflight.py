"""SC179: complete real-API metadata preflight, in retained synthetic roots only."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests._support import ROOT

REPO = ROOT
CASE_OUTPUT = None
EVENTS = []
ORIGINS = {}
NEGATIVE = []


def fixtures():
    spec = importlib.util.spec_from_file_location(
        'sc179_constructors', REPO/'tests/fixtures/sc179-restore-inventory-preflight/constructors.py')
    module = importlib.util.module_from_spec(spec)
    # Suppress even fixture bytecode; no module-global writes on discovery.
    with patch.object(sys, 'dont_write_bytecode', True):
        spec.loader.exec_module(module)
    return module


class ExternalImportStop(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'boto3', 'botocore', 'openai', 'anthropic', 'ollama'}:
            raise RuntimeError('SC179 unexpected external/model import')
        return None


@contextmanager
def product(root):
    """Inspected stdlib-only closure; reversible boundaries BEFORE first import."""
    before = dict(sys.modules)
    def stop(*args, **kwargs):
        raise RuntimeError('SC179 unexpected network or product child')
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
            stack.enter_context(patch.object(sys, 'path', [str(REPO/'src'), *sys.path]))
            stack.enter_context(patch.object(sys, 'meta_path', [ExternalImportStop(), *sys.meta_path]))
            stack.enter_context(patch.dict(os.environ, {'SKIPPERCAST_ROOT': str(root),
                                                       'SKIPPERCAST_HTTP_CACHE': '0'}))
            for name in ('getaddrinfo', 'create_connection'):
                stack.enter_context(patch.object(socket, name, stop))
            stack.enter_context(patch.object(socket.socket, 'connect', stop))
            stack.enter_context(patch.object(socket.socket, 'connect_ex', stop))
            stack.enter_context(patch.object(subprocess, 'Popen', stop))
            for name in ('system', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp'):
                if hasattr(os, name):
                    stack.enter_context(patch.object(os, name, stop))
            paths = importlib.import_module('skippercast.paths')
            stack.enter_context(patch.object(paths, 'repo_root', lambda: root))
            # If a peer imported contracts already, redirect constants AND bound defaults.
            prior = sys.modules.get('skippercast.platform.contracts')
            if prior is not None:
                old_root = prior.REPO
                stack.enter_context(patch.object(prior, 'REPO', root))
                for value in vars(prior).values():
                    defaults = getattr(value, '__defaults__', None)
                    if defaults and any(v is old_root for v in defaults):
                        stack.enter_context(patch.object(value, '__defaults__',
                            tuple(root if v is old_root else v for v in defaults)))
            cache = importlib.import_module('skippercast.seafloor.state_cache')
            http = importlib.import_module('skippercast.http')
            stack.enter_context(patch.object(http, 'default_session', stop))
            stack.enter_context(patch.object(http.Session, 'request', stop))
            for name, module in list(sys.modules.items()):
                if name.startswith('skippercast') and getattr(module, '__file__', None):
                    origin = Path(module.__file__).resolve()
                    if not origin.is_relative_to(REPO/'src'):
                        raise RuntimeError('SC179 unexpected product origin: ' + name)
                    ORIGINS[name] = str(origin)
            yield cache
    finally:
        # Restore import state as well as patches; synthetic bound roots cannot leak to peers.
        for name in sorted(set(sys.modules) - set(before), key=len, reverse=True):
            if name == 'skippercast' or name.startswith('skippercast.'):
                module = sys.modules.pop(name)
                parent, _, attr = name.rpartition('.')
                owner = sys.modules.get(parent)
                if owner is not None and getattr(owner, attr, None) is module:
                    delattr(owner, attr)


def snapshot(root):
    rows = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows[relative] = ['symlink', os.readlink(path)]
        elif path.is_file():
            rows[relative] = ['file', hashlib.sha256(path.read_bytes()).hexdigest()]
        else:
            rows[relative] = ['directory']
    return rows


class RestoreInventoryPreflightTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures()
        prefix = Path(CASE_OUTPUT or os.environ.get('TMPDIR', REPO.parent/'out/discovery'))
        prefix.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='sc179-', dir=prefix))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.cache = self.stack.enter_context(product(self.root))

    def event(self, name):
        EVENTS.append({'method': self._testMethodName, 'case': name})

    def child(self):
        return Path(tempfile.mkdtemp(prefix='case-', dir=self.root))

    def seed(self, root):
        for relative in ('reference/cells.json', 'screen/refresh-failure.json', 'reaches/r01/run.json'):
            path = root/'var/seafloor'/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'prior synthetic bytes\n')

    def assert_rejected_without_effects(self, files, scope='shared', include_cache=True, prepare=None):
        root = self.child()
        self.seed(root)
        if prepare:
            prepare(root)
        before = snapshot(root)
        s3 = self.f.MemoryS3(self.f.inventory(scope, files), scope)
        error = None
        def synthetic_restore(s3, bucket, destination, digest):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.f.PAYLOAD)
        with patch.object(self.cache, 'restore_private', side_effect=synthetic_restore) as restore, patch.object(Path, 'unlink') as unlink:
            try:
                self.cache.restore(s3, 'synthetic', root, scope, include_cache=include_cache)
            except (ValueError, KeyError, TypeError) as exc:
                error = exc
            # This is also the exact deciding assertion used by the bypass control.
            self.assertEqual((unlink.call_count, restore.call_count), (0, 0),
                             'metadata preflight side effects')
            self.assertIsInstance(error, ValueError, 'typed metadata rejection')
        self.assertEqual(snapshot(root), before, 'all prior state preserved')

    def bad_batches(self):
        f = self.f
        good = f.row('reference/run.json')
        bad = {
            'traversal': f.row('../outside.json'), 'absolute': f.row('/outside.json'),
            'other-scope': f.row('reaches/r01/run.json'),
            'alias': f.row('reference/./run.json'), 'empty-path': f.row(''),
            'path-null': f.row(None), 'path-list': f.row([]), 'path-number': f.row(4),
            'path-missing': {'sha256': f.DIGEST, 'bytes': len(f.PAYLOAD)},
            'hash-upper': f.row('reference/cells.json', sha256='A'*64),
            'hash-short': f.row('reference/cells.json', sha256='a'*63),
            'hash-long': f.row('reference/cells.json', sha256='a'*65),
            'hash-nonhex': f.row('reference/cells.json', sha256='g'*64),
            'hash-null': f.row('reference/cells.json', sha256=None),
            'hash-list': f.row('reference/cells.json', sha256=[]),
            'hash-missing': {'path': 'reference/cells.json', 'bytes': len(f.PAYLOAD)},
            'item-null': None, 'item-list': [], 'item-string': 'bad', 'item-number': 3,
            'duplicate': deepcopy(good),
        }
        for name, item in bad.items():
            for late in (False, True):
                yield name + ('-late' if late else '-first'), ([good, item] if late else [item, good]), 'shared', True
        # Repeat shape/hash/order cases with a valid cache row that bookkeeping skips.
        for name, item in bad.items():
            skipped_item = deepcopy(item)
            if isinstance(skipped_item, dict) and isinstance(skipped_item.get('path'), str):
                if skipped_item['path'] in ('reference/run.json', 'reference/cells.json'):
                    skipped_item['path'] = f.CACHE if name == 'duplicate' else 'cache/'+'b'*64+'/source.tif'
                elif name == 'other-scope':
                    skipped_item['path'] = 'reaches/r02/run.json'
            for late in (False, True):
                rows = [f.row(f.CACHE), skipped_item] if late else [skipped_item, f.row(f.CACHE)]
                yield 'skipped-'+name+('-late' if late else '-first'), rows, 'r01', False
        reach = f.row('reaches/r01/cells.json')
        for name, item in {
            'skipped-cache-hash': f.row(f.CACHE, sha256='bad'),
            'skipped-cache-path': f.row('cache/'+'a'*64+'/forbidden.json'),
            'skipped-cache-duplicate': f.row(f.CACHE),
        }.items():
            items = [f.row(f.CACHE), item] if name.endswith('duplicate') else [reach, item]
            for reverse in (False, True):
                yield name + ('-reverse' if reverse else '-forward'), (list(reversed(items)) if reverse else items), 'r01', False

    def test_regression(self):
        for name, files, scope, include in self.bad_batches():
            with self.subTest(case=name):
                self.assert_rejected_without_effects(files, scope, include)
                self.event(name)
        for name, files in [('files-null', None), ('files-dict', {}), ('files-string', ''), ('files-number', 3)]:
            with self.subTest(case=name):
                self.assert_rejected_without_effects(files)
                self.event(name)
        # Preserve baseline leaf refusal and resolved confinement, not a new
        # blanket prohibition on legitimate root/ancestor or internal aliases.
        for component in ('intermediate', 'leaf', 'dangling', 'outside'):
            with self.subTest(case='symlink-'+component):
                root = self.child()
                self.seed(root)
                target = root/'link-target'
                target.mkdir()
                base = root/'var/seafloor'
                if component in ('intermediate', 'outside'):
                    (base/'private-reaches').symlink_to(target, target_is_directory=True)
                else:
                    (base/'reference/run.json').symlink_to(
                        target/'missing' if component == 'dangling' else base/'reference/cells.json')
                path = 'private-reaches/r01/run.json' if component in ('intermediate', 'outside') else 'reference/run.json'
                scope = 'r01' if component in ('intermediate', 'outside') else 'shared'
                before = snapshot(root)
                with patch.object(self.cache, 'restore_private') as restore, patch.object(Path, 'unlink') as unlink:
                    with self.assertRaises(ValueError):
                        self.cache.restore(self.f.MemoryS3(self.f.inventory(scope, [self.f.row(path)]), scope),
                                           'synthetic', root, scope)
                    self.assertEqual((unlink.call_count, restore.call_count), (0, 0))
                self.assertEqual(snapshot(root), before)
                self.event('symlink-'+component)
        for include in (False, True):
            root = self.child()
            (root/'var/seafloor/cache').mkdir(parents=True)
            (root/'target').mkdir()
            (root/'var/seafloor/cache'/('a'*64)).symlink_to(root/'target', target_is_directory=True)
            s3 = self.f.MemoryS3(self.f.inventory('r01', [self.f.row(self.f.CACHE)]), 'r01')
            with self.subTest(case='cache-link-'+str(include)), patch.object(self.cache, 'restore_private') as restore:
                with self.assertRaises(ValueError):
                    self.cache.restore(s3, 'synthetic', root, 'r01', include_cache=include)
                restore.assert_not_called()
                self.event('cache-link-'+str(include))

    def test_compatibility(self):
        f = self.f
        for scope, paths in [('shared', []), ('shared', ['reference/run.json']),
                             ('shared', ['reference/run.json', 'reference/cells.json']),
                             ('shared', ['screen/refresh-failure.json']),
                             ('source-review', ['source-review/checkpoint.json']),
                             ('r01', [f.CACHE, 'reaches/r01/run.json', 'private-reaches/r01/cells.json'])]:
            for include in (False, True):
                label = 'valid-'+scope+'-'+','.join(paths)+'-'+str(include)
                with self.subTest(case=label):
                    source, destination = self.child(), self.child()
                    originals = []
                    for relative in paths:
                        path = source/'var/seafloor'/relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(f.PAYLOAD)
                        originals.append(path)
                    s3 = f.MemoryS3()
                    document = self.cache.save(s3, 'synthetic', source, scope, originals)
                    with patch.object(Path, 'unlink', autospec=True) as unlink, patch.object(
                            self.cache, 'restore_private', wraps=self.cache.restore_private) as restore:
                        self.assertIs(self.cache.restore(s3, 'synthetic', destination, scope, include_cache=include), True)
                        expected = [r['path'] for r in document['files'] if include or not r['path'].startswith('cache/')]
                        self.assertEqual([call.args[2].relative_to(destination/'var/seafloor').as_posix()
                                          for call in restore.call_args_list], expected)
                        marker = destination/'var/seafloor/screen/refresh-failure.json'
                        marker_calls = [call for call in unlink.call_args_list if call.args[0] == marker]
                        self.assertEqual(len(marker_calls), int(scope == 'shared' and 'screen/refresh-failure.json' not in paths))
                        for relative in expected:
                            self.assertEqual((destination/'var/seafloor'/relative).read_bytes(), f.PAYLOAD)
                    with patch.object(Path, 'unlink'), patch.object(self.cache, 'restore_private') as restore:
                        self.assertIs(self.cache.restore(s3, 'synthetic', destination, scope, include_cache=include), True)
                        restore.assert_not_called()
                    self.event(label)
        # These save-produced batches were accepted by the pinned implementation.
        # Root/ancestor aliases and in-base directory aliases must stay compatible.
        for component in ('ancestor', 'root', 'var', 'base', 'internal'):
            for paths in ([], ['reference/run.json', 'reference/cells.json'],
                          ['reference/run.json', 'screen/refresh-failure.json']):
                for include in (False, True):
                    label = 'valid-symlink-'+component+'-'+','.join(paths)+'-'+str(include)
                    with self.subTest(case=label):
                        source, container = self.child(), self.child()
                        originals = []
                        for relative in paths:
                            path = source/'var/seafloor'/relative
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(f.PAYLOAD)
                            originals.append(path)
                        s3 = f.MemoryS3()
                        document = self.cache.save(s3, 'synthetic', source, 'shared', originals)
                        real = container/'real'
                        real.mkdir()
                        if component in ('ancestor', 'root'):
                            (container/'alias').symlink_to(real, target_is_directory=True)
                            destination = container/'alias'
                            if component == 'ancestor':
                                (real/'child').mkdir()
                                destination /= 'child'
                        else:
                            destination = real
                            if component == 'var':
                                (container/'actual-var').mkdir()
                                (real/'var').symlink_to(container/'actual-var', target_is_directory=True)
                            elif component == 'base':
                                (container/'actual-base').mkdir()
                                (real/'var').mkdir()
                                (real/'var/seafloor').symlink_to(container/'actual-base', target_is_directory=True)
                            else:
                                target = real/'var/seafloor/reference-target'
                                target.mkdir(parents=True)
                                (real/'var/seafloor/reference').symlink_to(target, target_is_directory=True)
                        with patch.object(Path, 'unlink', autospec=True) as unlink, patch.object(
                                self.cache, 'restore_private', wraps=self.cache.restore_private) as restore:
                            self.assertIs(self.cache.restore(s3, 'synthetic', destination, 'shared', include_cache=include), True)
                            expected = [r['path'] for r in document['files']]
                            self.assertEqual([call.args[2].relative_to(destination/'var/seafloor').as_posix()
                                              for call in restore.call_args_list], expected)
                            marker = destination/'var/seafloor/screen/refresh-failure.json'
                            self.assertEqual(len([call for call in unlink.call_args_list if call.args[0] == marker]),
                                             int('screen/refresh-failure.json' not in paths))
                            for relative in expected:
                                self.assertEqual((destination/'var/seafloor'/relative).read_bytes(), f.PAYLOAD)
                        with patch.object(Path, 'unlink'), patch.object(self.cache, 'restore_private') as restore:
                            self.assertIs(self.cache.restore(s3, 'synthetic', destination, 'shared', include_cache=include), True)
                            restore.assert_not_called()
                        self.event(label)
        with self.subTest(case='missing'):
            self.assertIs(self.cache.restore(f.MemoryS3(), 'synthetic', self.child(), 'shared'), False)
            self.event('missing')
        for change in ('scope', 'version', 'oversized'):
            root = self.child()
            s3 = f.MemoryS3(f.inventory('shared', []))
            document = f.inventory('shared', [])
            document[change] = 'wrong'
            s3.objects['seafloor-cache/state/shared.json'] = b'x'*5_000_001 if change == 'oversized' else json.dumps(document).encode()
            with self.subTest(case=change), patch.object(Path, 'unlink') as unlink, patch.object(self.cache, 'restore_private') as restore:
                with self.assertRaises(ValueError):
                    self.cache.restore(s3, 'synthetic', root, 'shared')
                self.assertEqual((unlink.call_count, restore.call_count), (0, 0))
                self.event(change)
        with self.subTest(case='existing-byte-check'):
            root = self.child()
            s3 = f.MemoryS3(f.inventory('r01', [f.row('reaches/r01/run.json', bytes=len(f.PAYLOAD)+1)]), 'r01')
            s3.objects[f'seafloor-cache/{f.DIGEST}/run.json'] = f.PAYLOAD
            with patch.object(Path, 'unlink'), self.assertRaisesRegex(ValueError, 'size mismatch'):
                self.cache.restore(s3, 'synthetic', root, 'r01')
            self.event('existing-byte-check')
        with self.subTest(case='later-transfer-failure-not-rollback'):
            root = self.child()
            s3 = f.MemoryS3(f.inventory('r01', [f.row('reaches/r01/run.json'), f.row('reaches/r01/cells.json')]), 'r01')
            s3.objects[f'seafloor-cache/{f.DIGEST}/run.json'] = f.PAYLOAD
            s3.fail_key = f'seafloor-cache/{f.DIGEST}/cells.json'
            with patch.object(Path, 'unlink'), self.assertRaisesRegex(OSError, 'synthetic transfer failure'):
                self.cache.restore(s3, 'synthetic', root, 'r01')
            self.assertEqual((root/'var/seafloor/reaches/r01/run.json').read_bytes(), f.PAYLOAD)
            self.event('later-transfer-failure-not-rollback')

    def test_negative_control(self):
        files = [self.f.row('reference/run.json'), self.f.row('reference/cells.json', sha256='bad')]
        with patch.object(self.cache, '_preflight_restore', return_value=None):
            with self.assertRaisesRegex(AssertionError, 'metadata preflight side effects') as caught:
                self.assert_rejected_without_effects(files)
        NEGATIVE.append(str(caught.exception))
        self.event('bypass-detects-early-effects')
        self.assert_rejected_without_effects(files)
        self.event('restored-positive')

    def test_preservation(self):
        # Repeat every malformed metadata batch with all prior file/marker hashes checked.
        for name, files, scope, include in self.bad_batches():
            with self.subTest(case=name):
                self.assert_rejected_without_effects(files, scope, include)
                self.event('preserved-'+name)
        before = (dict(os.environ), socket.create_connection, subprocess.Popen, sys.path[:], sys.meta_path[:])
        root = self.child()
        with product(root):
            pass
        after = (dict(os.environ), socket.create_connection, subprocess.Popen, sys.path[:], sys.meta_path[:])
        self.assertEqual(after, before, 'harmless peer patch state')
        self.event('harmless-peer-before-after')


if __name__ == '__main__':
    unittest.main()

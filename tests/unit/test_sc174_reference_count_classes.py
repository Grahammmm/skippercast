"""SC174 full-module, offline aggregate-boundary regression tests.

No product imports, patches, environment changes or writes at collection time.
Every invocation retains its synthetic root; no retained evidence is deleted.
"""
from contextlib import ExitStack, contextmanager
import importlib
import importlib.abc
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from tests._support import ROOT as REPO
METHODS = ('test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation')


class OfflineViolation(RuntimeError):
    """An unexpected side effect is fatal, even if product code catches it."""


class NoModels(importlib.abc.MetaPathFinder):
    def __init__(self, events):
        self.events = events

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ollama', 'openai', 'anthropic'}:
            self.events.append('unexpected-model-import')
            raise OfflineViolation('Model import is not admitted')
        return None


@contextmanager
def offline_product(root):
    """Reversible guards before complete real module import; preserve peer state."""
    before_modules = {k for k in sys.modules if k == 'skippercast' or k.startswith('skippercast.')}
    before_attributes = {k: dict(vars(sys.modules[k])) for k in before_modules}
    before_path = list(sys.path)
    before_meta = list(sys.meta_path)
    events = []

    def deny(*args, **kwargs):
        events.append('unexpected-network-or-child')
        raise OfflineViolation(events[-1])

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
            stack.enter_context(patch.dict(os.environ, {'SKIPPERCAST_ROOT': str(root),
                                                       'SKIPPERCAST_HTTP_CACHE': '0'}))
            for obj, name in ((socket, 'create_connection'), (socket, 'getaddrinfo'),
                              (socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                              (subprocess, 'Popen'), (os, 'system'), (os, 'fork'),
                              (os, 'posix_spawn'), (os, 'posix_spawnp')):
                if hasattr(obj, name):
                    stack.enter_context(patch.object(obj, name, deny))
            sys.meta_path.insert(0, NoModels(events))
            # paths has no initialization effects. Override before contracts REPO
            # and its function defaults are evaluated, not after first import.
            paths = importlib.import_module('skippercast.paths')
            stack.enter_context(patch.object(paths, 'repo_root', lambda: root))
            contracts = importlib.import_module('skippercast.platform.contracts')
            stack.enter_context(patch.object(contracts, 'REPO', root))
            for name in ('load_catalogs', 'load_region', 'validate_region', 'requirement_report'):
                stack.enter_context(patch.object(getattr(contracts, name), '__defaults__', (root,)))
            grid = importlib.import_module('skippercast.seafloor.grid')
            stack.enter_context(patch.object(grid, 'REPO', root))
            stack.enter_context(patch.object(grid.build, '__defaults__', (root,)))
            http = importlib.import_module('skippercast.http')
            stack.enter_context(patch.object(http, 'repo_root', lambda: root))
            stack.enter_context(patch.object(http.Session, 'request', deny))
            stack.enter_context(patch.object(http, 'default_session', deny))
            stack.enter_context(patch.object(grid.reference.rasterio, 'open', deny))
            origins = {k: str(Path(v.__file__).resolve()) for k, v in sys.modules.items()
                       if k.startswith('skippercast') and getattr(v, '__file__', None)}
            if any(not Path(p).is_relative_to(REPO / 'src') for p in origins.values()):
                raise OfflineViolation('Product module imported from outside candidate')
            yield grid, origins, events
            if events:
                raise OfflineViolation('Unexpected safety sentinel event')
    finally:
        sys.path[:] = before_path
        sys.meta_path[:] = before_meta
        # importlib also attaches imported children to existing parent packages.
        # Restore that namespace, not only sys.modules, for ordinary peer suites.
        for name, original in before_attributes.items():
            namespace = vars(sys.modules[name])
            for key, value in list(namespace.items()):
                if isinstance(value, types.ModuleType) and value.__name__.startswith('skippercast'):
                    if key in original:
                        namespace[key] = original[key]
                    else:
                        del namespace[key]
        for name in list(sys.modules):
            if (name == 'skippercast' or name.startswith('skippercast.')) and name not in before_modules:
                del sys.modules[name]


@contextmanager
def no_filesystem():
    """No filesystem access (including reads) during the numerical API call."""
    events = []

    def deny(*args, **kwargs):
        events.append('filesystem-access')
        raise OfflineViolation(events[-1])

    with ExitStack() as stack:
        for target in ('builtins.open', 'io.open', 'os.open', 'os.stat', 'os.lstat',
                       'os.scandir', 'os.listdir', 'os.mkdir', 'os.makedirs',
                       'os.rename', 'os.replace', 'os.unlink', 'os.remove', 'os.rmdir'):
            stack.enter_context(patch(target, deny))
        yield
        if events:
            raise OfflineViolation('Filesystem access was attempted')


class ReferenceCountClassesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prefix = os.environ.get('SC174_OUTPUT_ROOT')
        if prefix:
            parent = Path(prefix)
        elif os.environ.get('CI'):
            parent = Path(tempfile.gettempdir())
        else:
            parent = REPO.parent / 'out' / 'discovery'
        parent.mkdir(parents=True, exist_ok=True)
        cls.run_root = Path(tempfile.mkdtemp(prefix='sc174-', dir=parent))
        cls.records = []
        cls.origins = {}

    @classmethod
    def tearDownClass(cls):
        (cls.run_root / 'subcases.json').write_text(json.dumps({
            'subcases': cls.records, 'origins': cls.origins,
        }, indent=2) + '\n')
        print('SC174 retained invocation:', cls.run_root)

    def setUp(self):
        self.environment = dict(os.environ)
        self.peer = (socket.create_connection, subprocess.Popen, list(sys.path),
                     list(sys.meta_path), sys.dont_write_bytecode)
        self.scope = ExitStack()
        self.addCleanup(self.scope.close)
        self.grid, origins, self.events = self.scope.enter_context(offline_product(self.run_root / 'synthetic'))
        self.origins.update(origins)
        # NumPy and native dependency imports occur under pre-import guards.
        import numpy as np
        self.np = np
        self.fixture = json.loads((REPO / 'tests/fixtures/sc174-reference-count-classes/patterns.json').read_text())

    @contextmanager
    def case(self, name):
        with self.subTest(case=name):
            try:
                yield
            except BaseException:
                self.records.append({'method': self._testMethodName, 'case': name, 'passed': False})
                raise
            else:
                self.records.append({'method': self._testMethodName, 'case': name, 'passed': True})

    def count(self, mosaic, n=2):
        with no_filesystem():
            return self.grid.cell_counts(mosaic, n)

    def reject(self, mosaic):
        # Shared deciding assertion: ordinary regression AND bypass control.
        with self.assertRaises(ValueError, msg='categorical preflight must reject input'):
            self.count(mosaic)

    def exact(self, mosaic, shallow=None, unknown=None, n=2):
        result = self.count(mosaic, n)
        self.assertEqual(len(result), 2)
        self.np.testing.assert_array_equal(result[0], self.fixture['shallow'] if shallow is None else shallow)
        self.np.testing.assert_array_equal(result[1], self.fixture['unknown'] if unknown is None else unknown)

    def test_regression(self):
        np = self.np
        valid = np.array([[0, 1], [2, 0]], dtype='int16')
        cases = {
            'negative': np.array([[-1, 1], [2, 0]], dtype='int16'),
            'three': np.array([[3, 1], [2, 0]], dtype='uint8'),
            '255': np.array([[255, 1], [2, 0]], dtype='uint8'),
            'boolean': np.array([[False, True], [True, False]]),
            'float-codes': valid.astype('float64'),
            'nan': np.array([[np.nan, 1], [2, 0]]),
            'object': valid.astype(object),
            'one-dimensional': valid.reshape(4),
            'three-dimensional': valid.reshape(1, 2, 2),
            'masked-valid': np.ma.array(valid, mask=[[True, False], [False, False]]),
            'masked-invalid': np.ma.array([[255, 1], [2, 0]], mask=[[True, False], [False, False]]),
        }
        for name, mosaic in cases.items():
            with self.case(name):
                self.reject(mosaic)
        with self.case('non-divisible'):
            with self.assertRaisesRegex(ValueError, 'align to full planning cells'):
                self.count(np.zeros((3, 2), dtype='uint8'))

    def test_compatibility(self):
        np = self.np
        for dtype in ('int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64'):
            with self.case(dtype):
                self.exact(np.array(self.fixture['mosaic'], dtype=dtype))
        with self.case('two-by-two'):
            self.exact(np.array([[0, 1], [2, 0]], dtype='uint8'), [[1]], [[2]])
        mosaic = np.array(self.fixture['mosaic'], dtype='uint8')
        expanded = np.repeat(np.repeat(mosaic, 2, axis=0), 2, axis=1)
        with self.case('noncontiguous'):
            view = expanded[::2, ::2]
            self.assertFalse(view.flags.c_contiguous)
            self.exact(view)
        with self.case('unmasked'):
            self.exact(np.ma.array(mosaic, mask=False))
        with self.case('unmasked-view'):
            self.exact(np.ma.array(expanded, mask=False)[::2, ::2])
        with self.case('producer-shaped'):
            producer = np.ones((10, 20), dtype='uint8')
            producer[:5, :10] = 2
            producer[5:, :10] = 0
            producer[:, 10:] = 2
            self.exact(producer, [[50, 100]], [[50, 0]], n=10)
        with self.case('empty'):
            result = self.count(np.zeros((0, 4), dtype='uint8'))
            self.assertEqual([r.shape for r in result], [(0, 2), (0, 2)])
        with self.case('numpy-block-size'):
            self.exact(mosaic, n=np.int64(2))

    def test_negative_control(self):
        np = self.np
        bad = np.array([[3, 1], [2, 0]], dtype='uint8')
        genuine = self.grid._validate_reference_mosaic
        with patch.object(self.grid, '_validate_reference_mosaic', lambda mosaic: None):
            with self.case('same-regression-detects-bypass'):
                with self.assertRaisesRegex(self.failureException, 'ValueError not raised'):
                    self.reject(bad)
            with self.case('returned-pair'):
                self.exact(bad, [[1]], [[1]])
        with self.case('restored-rejection'):
            self.assertIs(self.grid._validate_reference_mosaic, genuine)
            self.reject(bad)
        with self.case('restored-positive'):
            self.exact(np.array(self.fixture['mosaic'], dtype='uint8'))

    def test_preservation(self):
        np = self.np
        valid = np.array(self.fixture['mosaic'], dtype='uint8')
        invalid = valid.copy()
        invalid[0, 0] = 3
        masked = np.ma.array(valid.copy(), mask=False)
        masked.mask[0, 0] = True
        for name, a, rejection in (('valid-bytes', valid, False),
                                    ('invalid-bytes', invalid, True),
                                    ('masked-bytes', masked, True),
                                    ('unmasked-bytes', np.ma.array(valid.copy(), mask=False), False)):
            with self.case(name):
                before = (np.ma.getdata(a).tobytes(), np.ma.getmaskarray(a).tobytes(), a.shape, a.dtype, a.strides)
                self.reject(a) if rejection else self.exact(a)
                after = (np.ma.getdata(a).tobytes(), np.ma.getmaskarray(a).tobytes(), a.shape, a.dtype, a.strides)
                self.assertEqual(before, after)
        with self.case('read-only'):
            valid.flags.writeable = False
            self.exact(valid)
            self.assertFalse(valid.flags.writeable)
        with self.case('no-filesystem'):
            # Every count above also used the scoped strict filesystem guard.
            self.exact(valid)
            self.assertEqual(self.events, [])
            self.assertEqual(list((self.run_root).iterdir()), [])
        with self.case('peer-state'):
            self.scope.close()
            self.assertEqual(dict(os.environ), self.environment)
            self.assertEqual((socket.create_connection, subprocess.Popen, list(sys.path),
                              list(sys.meta_path), sys.dont_write_bytecode), self.peer)
            # Harmless peer executes before and after the same real import scope.
            class Peer(unittest.TestCase):
                def runTest(peer):
                    peer.assertEqual(dict(os.environ), self.environment)
                    peer.assertIs(socket.create_connection, self.peer[0])
                    peer.assertIs(subprocess.Popen, self.peer[1])
            for phase in ('before', 'after'):
                result = unittest.TestResult()
                Peer().run(result)
                self.assertTrue(result.wasSuccessful(), phase)
                if phase == 'before':
                    with offline_product(self.run_root / 'peer-synthetic'):
                        pass


if __name__ == '__main__':
    unittest.main(verbosity=2)

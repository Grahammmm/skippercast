"""SC173: real terrain APIs, offline, isolated, and ordinarily discoverable."""
from contextlib import contextmanager, ExitStack
import builtins
import copy
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

BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
BASE_SHA256 = 'd93d8a65a350927451eff74ccf0c38cd1c9a6bad811417c42374b61e02ce44e7'
REPO = Path(__file__).resolve().parents[2]
PRODUCT = 'src/skippercast/seafloor/terrain.py'
METHOD_CASES = {
    'test_regression': ['int_zero', 'int_one', 'int_two', 'int_mixed', 'uint_one',
                        'float', 'object', 'scalar_bool', 'scalar_int', 'python_bool',
                        'list', 'one_dimensional', 'three_dimensional', 'misaligned',
                        'boolean_positive'],
    'test_compatibility': ['plane_true_2', 'plane_true_25', 'plane_true_50', 'all_false',
                           'sparse_hole', 'nonfinite', 'noncontiguous', 'bump', 'support_and_radii'],
    'test_negative_control': ['broken_gate_same_assertion', 'restored_integer_refusal',
                              'restored_boolean_positive'],
    'test_preservation': ['success_true', 'success_false', 'success_hole', 'success_nonfinite',
                          'success_view'] + ['refusal_' + name for name in (
                              'int_zero', 'int_one', 'int_two', 'int_mixed', 'uint_one',
                              'float', 'object', 'scalar_bool', 'scalar_int', 'python_bool',
                              'list', 'one_dimensional', 'three_dimensional', 'misaligned')]
                         + ['peer_isolation'],
}


def denied(*args, **kwargs):
    raise RuntimeError('SC173 offline side-effect sentinel')


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm', 'transformers'}:
            denied()
        return None


@contextmanager
def offline():
    """Reversible guards before product import; dependencies may read installed bytes."""
    original_open, original_io_open, original_os_open = builtins.open, io.open, os.open

    def safe_open(file, mode='r', *args, **kwargs):
        if any(char in mode for char in 'wax+'):
            denied()
        return original_open(file, mode, *args, **kwargs)

    def safe_io_open(file, mode='r', *args, **kwargs):
        if any(char in mode for char in 'wax+'):
            denied()
        return original_io_open(file, mode, *args, **kwargs)

    def safe_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            denied()
        return original_os_open(path, flags, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
        stack.enter_context(patch.object(sys, 'meta_path', [NoModels(), *sys.meta_path]))
        for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                          (socket, 'create_connection'), (socket, 'getaddrinfo'),
                          (subprocess, 'Popen'), (os, 'system'), (os, 'popen'),
                          (os, 'fork'), (os, 'posix_spawn'), (os, 'posix_spawnp'),
                          (os, 'mkdir'), (os, 'remove'), (os, 'unlink'),
                          (os, 'rename'), (os, 'replace'), (os, 'rmdir')):
            if hasattr(obj, name):
                stack.enter_context(patch.object(obj, name, denied))
        stack.enter_context(patch.object(builtins, 'open', safe_open))
        stack.enter_context(patch.object(io, 'open', safe_io_open))
        stack.enter_context(patch.object(os, 'open', safe_os_open))
        yield


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('Missing complete-module loader')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def peer_state():
    return (dict(os.environ), list(sys.path), list(sys.meta_path), sys.dont_write_bytecode,
            builtins.open, io.open, os.open, os.mkdir, socket.socket.connect,
            socket.create_connection, subprocess.Popen)


class DerivativeMaskTests(unittest.TestCase):
    evidence_root = None
    records = []
    origins = []

    @classmethod
    def setUpClass(cls):
        # Full pinned module, not an extracted function or executed source string.
        # Immutable complete source exported from BASE:PRODUCT. This portable text
        # fixture also works in CI's shallow checkout without git history/network.
        raw = (REPO / 'tests/fixtures/sc173-derivative-mask/pinned_terrain.py.txt').read_bytes()
        if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
            raise ValueError('Pinned baseline product hash mismatch')
        # Closure inspected before any product import: package initializers are inert;
        # terrain imports only numpy and scipy.ndimage (no data roots/bound defaults).
        expected = {
            'src/skippercast/__init__.py': '"""SkipperCast: evidence for personal boat-fishing planning."""\n\n__version__ = "0.8.0"\n',
            'src/skippercast/seafloor/__init__.py': '"""Original-survey habitat pipeline. Reference compilations never earn a tier."""\n',
        }
        for name, content in expected.items():
            if (REPO / name).read_text() != content:
                raise ValueError('Product package initialization closure changed')
        # Do not import a broader platform module to redirect nonexistent data roots.
        # There is no platform.contracts dependency in this complete closure.
        cls.run_root = Path(tempfile.mkdtemp(prefix='sc173-', dir=cls.evidence_root))
        cls.baseline_path = cls.run_root / 'pinned_terrain.py'
        cls.baseline_path.write_bytes(raw)
        cls.before = peer_state()
        cls.records = []
        cls.origins = []
        cls.construct = load_file('sc173_constructors', REPO / 'tests/fixtures/sc173-derivative-mask/constructors.py')

    def setUp(self):
        self.before = peer_state()
        self.initial_product_modules = {k: v for k, v in sys.modules.items()
                                        if k == 'skippercast' or k.startswith('skippercast.')}
        self.stack = ExitStack()
        self.addCleanup(self.restore)
        self.stack.enter_context(patch.object(sys, 'path', [str(REPO / 'src'), *sys.path]))
        self.stack.enter_context(offline())
        self.np = importlib.import_module('numpy')
        self.terrain = importlib.import_module('skippercast.seafloor.terrain')
        self.baseline = load_file('sc173_pinned_terrain', self.baseline_path)
        if Path(self.terrain.__file__ or '').resolve() != REPO / PRODUCT:
            raise ValueError('Wrong product import origin')
        self.origins.append({name: str(Path(mod.__file__ or '').resolve()) for name, mod in (
            ('terrain', self.terrain), ('baseline', self.baseline),
            ('numpy', self.np), ('scipy', sys.modules['scipy']))})
        self.data = self.construct.grids(self.np)

    def restore(self):
        self.stack.close()
        for name in list(sys.modules):
            if (name == 'skippercast' or name.startswith('skippercast.')) and name not in self.initial_product_modules:
                del sys.modules[name]
        self.assertEqual(self.before, peer_state(), 'Peer environment/patch state changed')

    @classmethod
    def tearDownClass(cls):
        if cls.before != peer_state():
            raise AssertionError('Class leaked peer state')
        (cls.run_root / 'subcases.json').write_text(json.dumps(cls.records, indent=2) + '\n')
        print(f'SC173 subcases: {cls.run_root / "subcases.json"} ({len(cls.records)} executed)')

    @contextmanager
    def case(self, name):
        with self.subTest(case=name):
            record = {'id': self.id() + '/' + name, 'method': self._testMethodName,
                      'case': name, 'status': 'started'}
            self.records.append(record)
            try:
                yield
            except BaseException as exc:
                record.update(status='failed', exception=type(exc).__name__, reason=str(exc))
                raise
            else:
                record['status'] = 'passed'

    def assert_refused(self, depth, valid, *, broken=False):
        # Use wraps, not side-effect errors: an integer accepted by the broken gate
        # must execute real math before the SAME intended assertion fails.
        with patch.object(self.terrain, 'binary_erosion', wraps=self.terrain.binary_erosion) as erosion, \
             patch.object(self.terrain.np, 'gradient', wraps=self.terrain.np.gradient) as gradient:
            error = None
            try:
                self.terrain.derivatives(depth, valid, 25)
            except Exception as exc:
                error = exc
            if broken:
                self.assertIsNone(error, 'Broken gate failed for an unrelated reason')
                erosion.assert_called_once()
                gradient.assert_called_once()
            if error is None:
                self.fail('support mask accepted: expected ValueError')
            self.assertIsInstance(error, ValueError, f'Wrong refusal exception: {error!r}')
            erosion.assert_not_called()
            gradient.assert_not_called()

    def compare(self, depth, valid, resolution=25):
        actual = self.terrain.derivatives(depth, valid, resolution)
        expected = self.baseline.derivatives(depth, valid, resolution)
        self.assertEqual(set(actual), {'slope_deg', 'vrm', 'bpi_fine_m', 'bpi_broad_m'})
        for key in expected:
            self.np.testing.assert_array_equal(self.np.isnan(actual[key]), self.np.isnan(expected[key]))
            self.np.testing.assert_allclose(actual[key], expected[key], rtol=0, atol=0, equal_nan=True)
        return actual

    def test_regression(self):
        depth, good = self.data['true']
        for name, mask in self.construct.invalid_masks(self.np, depth.shape).items():
            with self.case(name):
                self.assert_refused(depth, mask)
        with self.case('boolean_positive'):
            result = self.compare(depth, good)
            self.assertTrue(self.np.isfinite(result['slope_deg'][10, 11]))

    def test_compatibility(self):
        for resolution in (2, 25, 50):
            with self.case(f'plane_true_{resolution}'):
                depth, valid = self.data['true']
                self.compare(depth, valid, resolution)
        for label, name in (('all_false', 'false'), ('sparse_hole', 'hole'),
                            ('nonfinite', 'nonfinite'), ('noncontiguous', 'view'), ('bump', 'bump')):
            with self.case(label):
                depth, valid = self.data[name]
                if name == 'view':
                    self.assertFalse(valid.flags.c_contiguous)
                result = self.compare(depth, valid)
                if name == 'false':
                    self.assertTrue(all(self.np.isnan(layer).all() for layer in result.values()))
                if name == 'nonfinite':
                    for y, x in ((7, 7), (10, 10), (13, 13)):
                        self.assertTrue(all(self.np.isnan(layer[y, x]) for layer in result.values()))
        with self.case('support_and_radii'):
            depth, valid = self.data['true']
            with patch.object(self.terrain, 'binary_erosion', wraps=self.terrain.binary_erosion) as erosion, \
                 patch.object(self.terrain, 'mean_full', wraps=self.terrain.mean_full) as mean:
                result = self.terrain.derivatives(depth, valid, 25)
            self.np.testing.assert_array_equal(erosion.call_args.kwargs['structure'], self.np.ones((3, 3)))
            self.assertEqual(erosion.call_args.kwargs['border_value'], 0)
            self.assertEqual([call.args[2] for call in mean.call_args_list], [3, 3, 3, 3, 9])
            self.assertTrue(self.np.isnan(result['slope_deg'][0]).all())
            self.assertTrue(self.np.isnan(result['vrm'][1]).all())
            self.assertTrue(self.np.isfinite(result['bpi_broad_m'][10, 11]))

    def test_negative_control(self):
        depth, good = self.data['true']
        integer = self.np.ones(depth.shape, dtype=self.np.int64)

        def permit_integer_mask(valid):
            return None

        with self.case('broken_gate_same_assertion'):
            with patch.object(self.terrain, '_validate_support_mask', permit_integer_mask):
                with self.assertRaisesRegex(AssertionError, '^support mask accepted: expected ValueError$'):
                    self.assert_refused(depth, integer, broken=True)
        with self.case('restored_integer_refusal'):
            self.assert_refused(depth, integer)
        with self.case('restored_boolean_positive'):
            self.compare(depth, good)

    def snapshot(self, value):
        if isinstance(value, self.np.ndarray):
            return (value.copy(), value.shape, value.dtype, value.strides)
        return copy.deepcopy(value)

    def unchanged(self, value, snapshot):
        if isinstance(value, self.np.ndarray):
            self.np.testing.assert_array_equal(value, snapshot[0])
            self.assertEqual((value.shape, value.dtype, value.strides), snapshot[1:])
        else:
            self.assertEqual(value, snapshot)

    def test_preservation(self):
        for name in ('true', 'false', 'hole', 'nonfinite', 'view'):
            with self.case('success_' + name):
                depth, valid = self.data[name]
                before = self.snapshot(depth), self.snapshot(valid)
                self.terrain.derivatives(depth, valid, 25)
                self.unchanged(depth, before[0])
                self.unchanged(valid, before[1])
        for name, valid in self.construct.invalid_masks(self.np, self.data['true'][0].shape).items():
            with self.case('refusal_' + name):
                depth = self.data['true'][0].copy()
                before = self.snapshot(depth), self.snapshot(valid)
                self.assert_refused(depth, valid)
                self.unchanged(depth, before[0])
                self.unchanged(valid, before[1])
        with self.case('peer_isolation'):
            # A harmless peer checks both sides of a nested scope; method cleanup
            # additionally checks the outer pre-import environment after every test.
            class HarmlessPeer(unittest.TestCase):
                expected: tuple = ()
                def runTest(peer):
                    peer.assertEqual(peer.expected, peer_state())
            peer = HarmlessPeer()
            peer.expected = peer_state()
            peer.runTest()
            with offline():
                self.terrain.derivatives(*self.data['true'], 25)
            peer.runTest()


if __name__ == '__main__':
    unittest.main()

"""SC145 parser-only checks. Importing this test installs no global patches.

Producer vocabulary: render/align.py measure_alignment and render/preview.py
preview/completed_result at the admitted base. These are synthetic documents,
not source acceptance, alignment qualification, or end-to-end render coverage.
"""
from contextlib import contextmanager, ExitStack
import builtins
import hashlib
import importlib
import importlib.abc
import io
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
RUN_ROOT = None  # standalone runner supplies its exclusive retained directory
CLOSURE = (
    'skippercast', 'skippercast.paths', 'skippercast.coastal',
    'skippercast.coastal.render', 'skippercast.coastal.render.align',
    'skippercast.coastal.render.mesh', 'skippercast.coastal.receipts',
    'skippercast.coastal.render.preview',
)
FORBIDDEN = {'boto3', 'botocore', 'openai', 'anthropic', 'ollama', 'requests',
             'httpx', 'numpy', 'rasterio', 'shapely', 'torch', 'transformers'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def denied(*args, **kwargs):
    raise RuntimeError('SC145 offline boundary: network/model/child/render forbidden')


class NoOperationalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in FORBIDDEN:
            raise RuntimeError('SC145 prohibited import')
        if fullname.startswith('skippercast.') and fullname not in CLOSURE:
            raise RuntimeError('SC145 unexpected product import')
        return None


@contextmanager
def offline_preview(root):
    """Scoped ordinary-test guards; no audit hook or persistent peer poisoning.

    The complete selected product closure imports only stdlib. No platform
    contracts or data-root-bound defaults occur in this closure. repo_root is
    redirected before importing the product closure in case that changes.
    """
    root = Path(root).resolve()
    read_roots = (REPO / 'src', REPO / 'tests/fixtures/sc145-preview-json-ambiguity',
                  Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve(), root)
    original_open, original_io_open, original_os_open = builtins.open, io.open, os.open
    original_mkdir = os.mkdir

    def check(path, writing=False):
        if isinstance(path, int):
            raise RuntimeError('SC145 descriptor open not admitted')
        resolved = Path(os.fsdecode(path)).resolve()
        roots = (root,) if writing else read_roots
        if not any(resolved.is_relative_to(base) for base in roots):
            raise RuntimeError('SC145 data access outside synthetic/runtime closure')

    def guarded_open(path, mode='r', *args, **kwargs):
        check(path, any(char in mode for char in 'wax+'))
        return original_open(path, mode, *args, **kwargs)

    def guarded_io_open(path, mode='r', *args, **kwargs):
        check(path, any(char in mode for char in 'wax+'))
        return original_io_open(path, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if kwargs.get('dir_fd') is not None:
            raise RuntimeError('SC145 relative descriptor open not admitted')
        check(path, bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        return original_os_open(path, flags, *args, **kwargs)

    def guarded_mkdir(path, *args, **kwargs):
        check(path, True)
        return original_mkdir(path, *args, **kwargs)

    old_bytecode = sys.dont_write_bytecode
    old_path = sys.path[:]
    finder = NoOperationalImports()
    try:
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(REPO / 'src'))
        sys.meta_path.insert(0, finder)
        with ExitStack() as stack:
            stack.enter_context(mock.patch('builtins.open', guarded_open))
            stack.enter_context(mock.patch('io.open', guarded_io_open))
            stack.enter_context(mock.patch('os.open', guarded_os_open))
            stack.enter_context(mock.patch('os.mkdir', guarded_mkdir))
            for name in ('system', 'popen', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp',
                         'spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve',
                         'spawnvp', 'spawnvpe', 'execl', 'execle', 'execlp', 'execlpe',
                         'execv', 'execve', 'execvp', 'execvpe', 'remove', 'unlink',
                         'rmdir', 'rename', 'replace', 'link', 'symlink'):
                if hasattr(os, name):
                    stack.enter_context(mock.patch.object(os, name, denied))
            stack.enter_context(mock.patch.object(subprocess, 'Popen', denied))
            stack.enter_context(mock.patch.object(socket, 'socket', denied))
            stack.enter_context(mock.patch.object(socket, 'create_connection', denied))
            stack.enter_context(mock.patch.object(socket, 'getaddrinfo', denied))
            paths = importlib.import_module('skippercast.paths')
            stack.enter_context(mock.patch.object(paths, 'repo_root', lambda: root))
            preview = importlib.import_module('skippercast.coastal.render.preview')
            for name in ('preview', 'main', 'build_mesh', 'render_png', 'publish_staging'):
                stack.enter_context(mock.patch.object(preview, name, denied))
            mesh = sys.modules['skippercast.coastal.render.mesh']
            for name in ('build_mesh', 'render_png'):
                stack.enter_context(mock.patch.object(mesh, name, denied))
            yield preview
    finally:
        sys.path[:] = old_path
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        sys.dont_write_bytecode = old_bytecode


def parse_constant_only_decoder(path):
    """Named old-behavior control; never edits source or replaces a module."""
    def reject(value):
        raise ValueError('nonfinite_json')
    return json.loads(Path(path).read_text(), parse_constant=reject)


class SC145PreviewJSON(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = RUN_ROOT
        # Discovery inherits its test process's TMPDIR. Retain evidence, no cleanup.
        cls.root = Path(tempfile.mkdtemp(prefix='sc145-tests-', dir=parent))
        cls.records = []
        cls.controls = {}
        cls.prior_product = {name for name in sys.modules if name == 'skippercast' or name.startswith('skippercast.')}
        cls.boundary = offline_preview(cls.root)
        cls.preview = cls.boundary.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.boundary.__exit__(None, None, None)

    def setUp(self):
        self.case_root = self.root / self._testMethodName
        self.case_root.mkdir()
        self.sentinel = self.case_root / 'output-sentinel.txt'
        self.sentinel.write_bytes(b'unchanged synthetic prior output\n')
        self.sentinel_before = sha(self.sentinel)
        self.inputs = []

    def tearDown(self):
        for path, before in self.inputs + [(self.sentinel, self.sentinel_before)]:
            after = sha(path)
            self.assertEqual(before, after, 'input/output sentinel changed')
            self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))
            self.records.append({'test': self.id(), 'path': str(path.relative_to(self.root)),
                                 'before': before, 'after': after})

    def payload(self, raw):
        path = self.case_root / ('input-' + str(len(self.inputs)) + '.json')
        path.write_bytes(raw.encode('utf-8') if isinstance(raw, str) else raw)
        self.inputs.append((path, sha(path)))
        return path

    def decoded(self, raw):
        return self.preview.read_json(self.payload(raw))

    def rejected(self, raw, code):
        with self.assertRaises(ValueError) as observed:
            self.decoded(raw)
        self.assertEqual(str(observed.exception), code)

    def test_preflight(self):
        loaded = {name for name in sys.modules if name == 'skippercast' or name.startswith('skippercast.')}
        self.assertTrue(set(CLOSURE) <= loaded)
        self.assertTrue(loaded - self.prior_product <= set(CLOSURE))
        for name in CLOSURE:
            self.assertTrue(Path(str(sys.modules[name].__file__)).resolve().is_relative_to(REPO / 'src'))
        self.assertEqual(sys.modules['skippercast.paths'].repo_root(), self.root.resolve())
        self.assertTrue(sys.dont_write_bytecode)
        self.assertEqual(self.decoded('{"finite":1}'), {'finite': 1})

    def test_valid_shapes(self):
        raws = ['null', 'true', 'false', '0', '"sea \\u6d77"', '[]', '{}',
                '[true,false,null,{"sea":"海", "nested":[1,2.5]}]',
                '{"state":"done","State":"held","state ":null,"sha256":"a","sha256x":"b","é":1,"é":2}']
        for raw in raws:
            with self.subTest(raw=raw):
                self.assertEqual(self.decoded(raw), json.loads(raw))

    def test_finite_spellings(self):
        for raw in ['0', '-0', '1', '-7', '9007199254740993', '1' + '0' * 500,
                    '0.0', '-0.0', '1.00', '1e3', '1E+03', '1e-999', '-1e-999',
                    '1.7976931348623157e308', '-1.7976931348623157e308', '5e-324']:
            with self.subTest(spelling=raw):
                expected, actual = json.loads(raw), self.decoded(raw)
                self.assertIs(type(actual), type(expected))
                self.assertEqual(actual, expected)
                if isinstance(actual, float):
                    self.assertTrue(math.isfinite(actual))
                    self.assertEqual(math.copysign(1, actual), math.copysign(1, expected))
                self.assertEqual(self.decoded('[' + raw + ',{"n":' + raw + '}]'), [expected, {'n': expected}])

    def test_duplicates(self):
        for raw in ['{"state":"held","state":"done"}', '{"state":"done","state":"done"}',
                    '{"artifact":{"sha256":"a","sha256":"b"}}',
                    '{"artifact":{"sha256":"a","sha256":"a"}}',
                    '[{"state":0,"state":1}]', '{"state":1,"sta\\u0074e":2}',
                    '[' * 40 + '{"sha256":null,"sha256":null}' + ']' * 40]:
            with self.subTest(case=len(self.inputs)):
                self.rejected(raw, 'duplicate_json_key')
        self.assertEqual(self.decoded('[{"state":1},{"state":2}]'), [{'state': 1}, {'state': 2}])

    def test_named_nonfinite(self):
        for token in ['NaN', 'Infinity', '-Infinity']:
            for raw in [token, '[' + token + ']', '{"v":' + token + '}', '{"v":[{"n":' + token + '}]}']:
                with self.subTest(case=len(self.inputs)):
                    self.rejected(raw, 'nonfinite_json')
        self.assertEqual(self.decoded('["NaN","Infinity","-Infinity"]'), ['NaN', 'Infinity', '-Infinity'])

    def test_overflow(self):
        for token in ['1e999', '-1e999', '1E+999', '-1.8e308']:
            for raw in [token, '[' + token + ']', '{"v":' + token + '}', '{"v":[{"n":' + token + '}]}']:
                with self.subTest(case=len(self.inputs)):
                    self.rejected(raw, 'nonfinite_json')
        self.assertEqual(self.decoded('"1e999"'), '1e999')

    def test_malformed(self):
        for raw in [b'"\xff"', '', '{', '[1,]', '{"a":1} trailing', '01', 'infinity', 'nan']:
            with self.subTest(case=len(self.inputs)):
                with self.assertRaises(ValueError):
                    self.decoded(raw)

    def test_byte_bound(self):
        cap = 2 * 1024 * 1024
        for length in [cap - 1, cap]:
            raw = '0' + ' ' * (length - 1)
            self.assertEqual(len(raw.encode('utf-8')), length)
            self.assertEqual(self.decoded(raw), 0)
        self.rejected('0' + ' ' * cap, 'json_byte_bound')
        # The bound is bytes, not characters; on-cap Unicode text still decodes.
        raw = '"海"' + ' ' * (cap - len('"海"'.encode('utf-8')))
        self.assertEqual(self.decoded(raw), '海')
        self.rejected(raw + ' ', 'json_byte_bound')

    def test_alignment_shape(self):
        identity = {'sha256': '0' * 64, 'bytes': 128}
        document = {'schema': 'alignment-receipt-v1', 'status': 'ready', 'holds': [],
                    'terrain': identity, 'imagery': identity,
                    'control_points': [{'terrain_pixel': [0, 0], 'imagery_pixel': [0, 0]},
                                       {'terrain_pixel': [1, 0], 'imagery_pixel': [1, 0]},
                                       {'terrain_pixel': [0, 1], 'imagery_pixel': [0, 1]},
                                       {'terrain_pixel': [1, 1], 'imagery_pixel': [1, 1]}],
                    'control_point_convention': 'pixel_center',
                    'method': 'reviewed_corresponding_controls_georeferencing',
                    'correspondence': None, 'photogrammetric_alignment_verified': False,
                    'footprint_overlap_fraction': 1.0, 'minimum_overlap': 0.95,
                    'max_residual_m': 0.0, 'residuals_m': [0.0] * 4,
                    'terrain_resolution_m': 1.0, 'maximum_residual_cells': 0.5,
                    'limitations': ['Synthetic parser fixture; not accepted alignment.']}
        self.assertEqual(self.decoded(json.dumps(document)), document)

    def test_completion_shapes(self):
        binding = '1' * 64
        documents = [
            {'schema': 'coastal-render-staging-v1', 'binding': binding},
            {'schema': 'coastal-render-complete-v1', 'binding': binding,
             'receipt': {'sha256': '0' * 64, 'bytes': 128}},
            {'schema': 'coastal-render-preview-v1', 'state': 'done', 'holds': [],
             'render_binding': binding, 'slice_id': 'synthetic', 'private_preview_ready': True,
             'publication_or_fishing_approval': False, 'synthetic': True,
             'product_integration': {'state': 'held', 'holds': ['product_loader_support_contract_unavailable']},
             'artifacts': [{'path': 'private/measured-mesh.npz', 'sha256': '0' * 64, 'bytes': 128,
                            'format': 'npz', 'contract': 'coastal-measured-mesh-v1'},
                           {'path': 'private/preview.png', 'sha256': '1' * 64, 'bytes': 128,
                            'format': 'png', 'contract': 'coastal-fixed-preview-png-v1'}]},
            {'schema': 'coastal-render-preview-v1', 'state': 'held', 'holds': ['slice_not_accepted'],
             'artifacts': [], 'publication_or_fishing_approval': False},
        ]
        for document in documents:
            self.assertEqual(self.decoded(json.dumps(document)), document)

    def test_negative_control(self):
        candidate = self.preview.read_json
        finite = self.payload('{"state":"done","n":[1,2.5,null]}')
        duplicate = self.payload('{"state":"held","state":"done"}')
        overflow = self.payload('{"n":1e999}')
        expected = {'state': 'done', 'n': [1, 2.5, None]}
        self.assertEqual(candidate(finite), expected)
        inner = {}
        # Each deciding assertion is isolated and must actually fail on old behavior.
        with mock.patch.object(self.preview, 'read_json', parse_constant_only_decoder):
            self.assertEqual(self.preview.read_json(finite), expected)
            for name, path in [('duplicate', duplicate), ('overflow', overflow)]:
                try:
                    with self.assertRaises(ValueError):
                        self.preview.read_json(path)
                except AssertionError as error:
                    inner[name] = {'detected': True, 'inner_assertion': str(error)}
                else:
                    self.fail('old-behavior control did not trigger the assertion')
        self.assertIs(self.preview.read_json, candidate)
        self.assertEqual(candidate(finite), expected)
        for path in [duplicate, overflow]:
            with self.assertRaises(ValueError):
                candidate(path)
        self.controls.update(mutant_detected=True, positive_passed=True, inner_failures=inner)

"""Offline complete-API checks for strict source-review checkpoint JSON (SC17C).

Safe under ordinary unittest discovery: no product imports, fixtures, process-wide
hooks or environment edits at import time. Each method retains its own newly
allocated synthetic tree below the output prefix or the inherited temp root.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import importlib.abc
import importlib.util
import inspect
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

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'src/skippercast/seafloor/source_review.py'
METHODS = ('test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation')
# A fixed, timezone-aware clock (same instant as tests._support.NOW).
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


class OfflineViolation(RuntimeError):
    """Unexpected external effect: never an expected product refusal."""


def forbidden(*args, **kwargs):
    raise OfflineViolation('SC17C STOP: external effect prohibited')


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm', 'transformers'}:
            raise OfflineViolation('SC17C STOP: model import prohibited')
        return None


def ambient_state():
    return (dict(os.environ), tuple(sys.path), tuple(sys.meta_path), sys.dont_write_bytecode,
            socket.getaddrinfo, socket.create_connection, socket.socket.connect,
            subprocess.Popen, os.system, io.open)


@contextmanager
def offline_product(root):
    """Inspected closure only; reversible sentinels are not a hostile-code sandbox.

    paths/package initializers are inert. contracts binds REPO and root defaults
    at import; seafloor.io imports http (no session at startup). All bindings are
    redirected to the synthetic root and restored, even on first import here.
    """
    before = ambient_state()
    modules_before = set(sys.modules)
    finder = NoModels()
    defaults = []
    contracts = None
    paths = None
    original_contract_repo = None
    resolver = socket.getaddrinfo
    original_http_resolver = None
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
            stack.enter_context(patch.object(sys, 'path', [str(REPO / 'src'), *sys.path]))
            sys.meta_path.insert(0, finder)
            for owner, name in ((socket, 'getaddrinfo'), (socket, 'create_connection'),
                                (socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                                (subprocess, 'Popen'), (os, 'system'), (os, 'popen'),
                                (os, 'fork'), (os, 'posix_spawn'), (os, 'posix_spawnp')):
                if hasattr(owner, name):
                    stack.enter_context(patch.object(owner, name, forbidden))
            real_io_open, real_os_open = io.open, os.open

            def checked_path(value):
                if not isinstance(value, int) and not Path(value).resolve().is_relative_to(root.resolve()):
                    raise OfflineViolation('SC17C STOP: write outside synthetic root')

            def safe_open(file, mode='r', *args, **kwargs):
                if any(c in mode for c in 'wax+'):
                    checked_path(file)
                return real_io_open(file, mode, *args, **kwargs)

            def safe_os_open(file, flags, *args, **kwargs):
                if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                    checked_path(file)
                return real_os_open(file, flags, *args, **kwargs)

            stack.enter_context(patch('builtins.open', safe_open))
            stack.enter_context(patch.object(io, 'open', safe_open))
            stack.enter_context(patch.object(os, 'open', safe_os_open))
            paths = importlib.import_module('skippercast.paths')
            original_repo = paths.repo_root()
            stack.enter_context(patch.object(paths, 'repo_root', lambda: root))
            contracts = importlib.import_module('skippercast.platform.contracts')
            original_contract_repo = (contracts.REPO if 'skippercast.platform.contracts' in modules_before
                                      else original_repo)
            for value in vars(contracts).values():
                if inspect.isfunction(value) and value.__module__ == contracts.__name__ and value.__defaults__:
                    old = value.__defaults__
                    restore = tuple(original_contract_repo if v == root else v for v in old)
                    defaults.append((value, restore))
                    value.__defaults__ = tuple(root if v == contracts.REPO else v for v in old)
            contracts.REPO = root
            http = importlib.import_module('skippercast.http')
            original_http_resolver = (http.Session.__init__.__kwdefaults__['resolver']
                                      if 'skippercast.http' in modules_before else resolver)
            http.Session.__init__.__kwdefaults__['resolver'] = forbidden
            stack.enter_context(patch.object(http, 'repo_root', lambda: root))
            stack.enter_context(patch.object(http, 'default_session', forbidden))
            module = importlib.import_module('skippercast.seafloor.source_review')
            if Path(module.__file__).resolve() != SOURCE:
                raise OfflineViolation('SC17C STOP: wrong product module origin')
            if contracts.REPO != root or contracts.load_region.__defaults__ != (root,):
                raise OfflineViolation('SC17C STOP: unredirected bound defaults')
            yield module
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for function, old in defaults:
            function.__defaults__ = old
        if contracts is not None:
            contracts.REPO = original_contract_repo
            if 'skippercast.platform.contracts' not in modules_before and paths is not None:
                contracts.repo_root = paths.repo_root
        http = sys.modules.get('skippercast.http')
        if http is not None and original_http_resolver is not None:
            http.Session.__init__.__kwdefaults__['resolver'] = original_http_resolver
            if 'skippercast.http' not in modules_before and paths is not None:
                http.repo_root = paths.repo_root
        if ambient_state() != before:
            raise OfflineViolation('SC17C STOP: ambient state not restored')


def ordinary_json_loads(text):
    """Ordinary last-wins, non-finite-accepting json.loads; only a reversible control seam."""
    return json.loads(text)


class SourceReviewJsonTests(unittest.TestCase):
    output_prefix = None
    records = []
    preservation = []
    negative_control = []
    origins = {}
    fixture_hashes = []

    def setUp(self):
        # CI may supply tempfile.tempdir/TMPDIR; do not override that ownership.
        parent = self.output_prefix or tempfile.gettempdir()
        self.root = Path(tempfile.mkdtemp(prefix='sc17c-', dir=parent))
        self.guards = offline_product(self.root)
        self.product = self.guards.__enter__()
        self.addCleanup(self.guards.__exit__, None, None, None)
        spec = importlib.util.spec_from_file_location(
            'sc17c_constructors', REPO / 'tests/fixtures/sc17c-source-review-json/constructors.py')
        self.fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fixtures)
        for name, module in list(sys.modules.items()):
            if name.startswith('skippercast') and getattr(module, '__file__', None):
                type(self).origins[name] = str(Path(module.__file__).resolve())
        self.counter = 0

    @contextmanager
    def case(self, name):
        with self.subTest(case=name):
            try:
                yield
            except BaseException:
                type(self).records.append({'method': self._testMethodName, 'case': name, 'ok': False})
                raise
            else:
                type(self).records.append({'method': self._testMethodName, 'case': name, 'ok': True})

    # Synthetic state -----------------------------------------------------

    def tree(self, label):
        """A fresh writer-shaped tree plus one genuine recorder-produced review row."""
        self.counter += 1
        root = self.fixtures.build_tree(self.root / f'{self.counter:03d}-{label.replace(":", "-")}')
        summary = self.product.record(root, self.fixtures.MANIFEST, 'tested', ['r01'],
                                      self.fixtures.OUTCOME, self.fixtures.EVIDENCE,
                                      now=NOW, note=self.fixtures.NOTE)
        self.assertEqual(summary['source_id'], 'tested')
        path = root / self.product.RELATIVE
        row = json.loads(path.read_text())['reviews'][0]
        return root, path, row

    def place(self, path, text):
        path.write_text(text)
        type(self).fixture_hashes.append({'path': str(path), 'sha256': self.fixtures.digest(path)})
        return path

    def malformed(self, name):
        root, path, row = self.tree(name)
        self.place(path, self.fixtures.malformed(name, row, self.product.digest))
        return root, path

    def partition(self, root, reaches=('r01',), now=NOW, queue=None):
        queue = list(queue if queue is not None else deepcopy(self.fixtures.QUEUE))
        return self.product.partition(root, self.fixtures.MANIFEST, queue, reaches, now=now)

    # Deciding assertion, reused literally by regression and the control ----

    def assert_refused(self, root):
        queue = [dict(item) for item in self.fixtures.QUEUE]
        with patch.object(self.product, 'context', wraps=self.product.context) as context:
            with self.assertRaises(ValueError):
                self.product.load(root)
            active, deferred, warnings = self.product.partition(
                root, self.fixtures.MANIFEST, queue, ('r01',), now=NOW)
            self.assertEqual(active, [dict(item) for item in self.fixtures.QUEUE])
            self.assertEqual(deferred, [])
            self.assertEqual(warnings, [self.fixtures.WARNING])
            context.assert_not_called()

    def assert_valid_defers_own_lead(self, root):
        active, deferred, warnings = self.partition(root)
        self.assertEqual(active, [{'id': 'untested'}])
        self.assertEqual([item['id'] for item in deferred], ['tested'])
        self.assertEqual(deferred[0]['review_outcome'], self.fixtures.OUTCOME)
        self.assertEqual(deferred[0]['review_note'], self.fixtures.NOTE)
        self.assertEqual(warnings, [])

    # Required methods -----------------------------------------------------

    def test_regression(self):
        for name in self.fixtures.MALFORMED:
            with self.case(f'malformed:{name}'):
                root, _ = self.malformed(name)
                self.assert_refused(root)

    def test_compatibility(self):
        with self.case('absent-default'):
            root = self.fixtures.build_tree(self.root / 'absent')
            self.assertFalse((root / self.product.RELATIVE).exists())
            self.assertEqual(self.product.load(root), {'version': 1, 'reviews': []})
            self.assertEqual(self.partition(root), (list(self.fixtures.QUEUE), [], []))
        with self.case('writer-shaped-identical'):
            root, path, _ = self.tree('writer')
            loaded = self.product.load(root)
            self.assertEqual(loaded, json.loads(path.read_text()))
            self.assertEqual(loaded, self.product.read_json(path))
            self.assertEqual(json.dumps(loaded, ensure_ascii=False, allow_nan=False, indent=2) + '\n',
                             path.read_text())
        with self.case('writer-shaped-defers-own-lead'):
            root, _, _ = self.tree('defer')
            self.assert_valid_defers_own_lead(root)
        with self.case('writer-rerecord-replaces-own-row'):
            root, _, _ = self.tree('rerecord')
            self.product.record(root, self.fixtures.MANIFEST, 'tested', ['r01', 'r02'],
                                self.fixtures.OUTCOME, self.fixtures.EVIDENCE,
                                now=NOW, note=self.fixtures.NOTE)
            reviews = self.product.load(root)['reviews']
            self.assertEqual([(r['source_id'], r['reach_ids']) for r in reviews],
                             [('tested', ['r01', 'r02'])])
        for literal in self.fixtures.FINITE:
            with self.case(f'finite-number:{literal}'):
                root, path, row = self.tree('finite')
                self.place(path, self.fixtures.finite(literal, row, self.product.digest))
                self.assertEqual(self.product.load(root)['reviews'][0]['evidence']['document']['marker'],
                                 json.loads(literal))
                self.assert_valid_defers_own_lead(root)
        with self.case('distinct-case-keys-accepted'):
            root, path, row = self.tree('case-keys')
            row['evidence']['document']['Marker'] = 1
            row['evidence']['document']['marker'] = 2
            row['evidence']['document_sha256'] = self.product.digest(row['evidence']['document'])
            self.place(path, json.dumps({'version': 1, 'reviews': [row]}))
            self.assert_valid_defers_own_lead(root)
        with self.case('scope-mismatch'):
            root, _, _ = self.tree('scope')
            self.assertEqual(self.partition(root, reaches=('r02',))[:2], (list(self.fixtures.QUEUE), []))
        with self.case('expired'):
            root, _, _ = self.tree('expired')
            self.assertEqual(self.partition(root, now=NOW + timedelta(days=7))[:2],
                             (list(self.fixtures.QUEUE), []))
        with self.case('future-review'):
            root, _, _ = self.tree('future')
            self.assertEqual(self.partition(root, now=NOW - timedelta(seconds=1))[:2],
                             (list(self.fixtures.QUEUE), []))
        with self.case('oversize-refused'):
            root, path, row = self.tree('oversize')
            text = json.dumps({'version': 1, 'reviews': [row]})
            self.place(path, text + ' ' * (self.product.MAX_BYTES + 1 - len(text.encode())))
            self.assertEqual(path.stat().st_size, self.product.MAX_BYTES + 1)
            with self.assertRaisesRegex(ValueError, 'Unsafe source-review checkpoint'):
                self.product.load(root)
            self.assert_refused(root)
        with self.case('exact-size-bound-accepted'):
            root, path, row = self.tree('exact-size')
            text = json.dumps({'version': 1, 'reviews': [row]})
            self.place(path, text + ' ' * (self.product.MAX_BYTES - len(text.encode())))
            self.assertEqual(path.stat().st_size, self.product.MAX_BYTES)
            self.assert_valid_defers_own_lead(root)
        with self.case('symlink-refused'):
            root, path, _ = self.tree('symlink')
            real = path.with_name('real.json')
            path.rename(real)
            path.symlink_to(real.name)
            with self.assertRaisesRegex(ValueError, 'Unsafe source-review checkpoint'):
                self.product.load(root)
            self.assert_refused(root)
        for label, document in (('wrong-version', {'version': 2, 'reviews': []}),
                                ('version-not-int', {'version': '1', 'reviews': []}),
                                ('reviews-not-list', {'version': 1, 'reviews': {}}),
                                ('top-level-list', [])):
            with self.case(label):
                root, path, _ = self.tree(label)
                self.place(path, json.dumps(document))
                with self.assertRaisesRegex(ValueError, 'Invalid source-review checkpoint'):
                    self.product.load(root)
                self.assert_refused(root)
        with self.case('not-json'):
            root, path, _ = self.tree('not-json')
            self.place(path, 'not JSON')
            self.assert_refused(root)

    def test_negative_control(self):
        root, path = self.malformed('duplicate-reviews')
        before = self.fixtures.snapshot(root)
        with self.case('ordinary-json-detected'):
            with patch.object(self.product, '_decode_checkpoint', ordinary_json_loads):
                with self.assertRaisesRegex(AssertionError, 'ValueError not raised') as caught:
                    self.assert_refused(root)
                # Ordinary last-wins decoding really does suppress the lead.
                self.assert_valid_defers_own_lead(root)
            type(self).negative_control.append({
                'detected': True, 'inner_assertion': str(caught.exception),
                'decoder': 'ordinary_json_loads', 'fixture': 'duplicate-reviews'})
            self.assertEqual(before, self.fixtures.snapshot(root))
        with self.case('ordinary-json-sweep'):
            detected = {}
            for name in self.fixtures.MALFORMED:
                sweep_root, _ = self.malformed(name)
                with patch.object(self.product, '_decode_checkpoint', ordinary_json_loads):
                    try:
                        self.assert_refused(sweep_root)
                    except AssertionError as error:
                        detected[name] = 'ValueError not raised' in str(error)
                    else:
                        detected[name] = False
            self.assertEqual(detected, {name: True for name in self.fixtures.MALFORMED})
            type(self).negative_control[-1]['sweep'] = detected
        with self.case('restored-refused'):
            self.assertIsNot(self.product._decode_checkpoint, ordinary_json_loads)
            self.assert_refused(root)
            self.assertEqual(before, self.fixtures.snapshot(root))
        with self.case('restored-valid-positive'):
            valid, _, _ = self.tree('control-positive')
            self.assert_valid_defers_own_lead(valid)

    def test_preservation(self):
        for name in self.fixtures.MALFORMED:
            with self.case(f'preserve:{name}'):
                root, path = self.malformed(name)
                before = self.fixtures.snapshot(root)
                raw = path.read_bytes()
                queue = [dict(item) for item in self.fixtures.QUEUE]
                frozen_queue = deepcopy(queue)
                with ExitStack() as stack:
                    writes = stack.enter_context(patch.object(
                        self.product, 'atomic_json', wraps=self.product.atomic_json))
                    context = stack.enter_context(patch.object(
                        self.product, 'context', wraps=self.product.context))
                    active, deferred, _ = self.product.partition(
                        root, self.fixtures.MANIFEST, queue, ('r01',), now=NOW)
                    with self.assertRaises(ValueError):
                        self.product.record(root, self.fixtures.MANIFEST, 'untested', ['r01'],
                                            self.fixtures.OUTCOME, self.fixtures.EVIDENCE,
                                            now=NOW, note=self.fixtures.NOTE)
                    writes.assert_not_called()
                    # partition never hashes context; record does before its load refusal.
                    self.assertEqual(context.call_count, 1)
                self.assertEqual(queue, frozen_queue)
                self.assertEqual(active, frozen_queue)
                self.assertTrue(all(a is q for a, q in zip(active, queue)))
                self.assertEqual(deferred, [])
                after = self.fixtures.snapshot(root)
                self.assertEqual(before, after)
                self.assertEqual(raw, path.read_bytes())
                type(self).preservation.append({'case': name, 'path': str(root),
                                                'before': before, 'after': after})


if __name__ == '__main__':
    unittest.main(verbosity=2)

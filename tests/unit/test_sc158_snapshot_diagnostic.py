"""SC158: noncentral held diagnostics hash only a no-follow regular snapshot leaf.

Offline, synthetic checks of ``skippercast.seafloor.scoped.load_snapshot``. Each
fixture lives in a fresh temporary root (the runner's admitted output root, the
candidate's sibling ``out/`` directory, or the inherited temporary directory in
CI), never under ``tests/fixtures``. Every patch is fixture-scoped and reversible;
nothing here writes, installs hooks or changes the environment at import time.
"""
import builtins
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'src'
FIXTURES = REPO / 'tests' / 'fixtures' / 'sc158-snapshot-diagnostic'
RUNNER = REPO / 'tools' / 'run_sc158_snapshot_diagnostic.py'
OUT_ENV = 'SC158_OUT_ROOT'
UNSAFE = 'unsafe scope snapshot diagnostic'
SCOPE_ID = 'sc158-demo'
REACH = 'demo-reach'
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
CHUNK_LIMIT = 1024 * 1024
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

REQUIRED_TESTS = ('test_positive_contract', 'test_rejects_malformed', 'test_baseline_compatibility',
                  'test_isolation_and_discovery', 'test_deciding_negative_control')
POSITIVE_CASES = ('absent-snapshot', 'absent-screen-dir', 'tiny-regular-snapshot',
                  'streamed-multi-chunk-snapshot', 'central-default-delegates', 'central-config-delegates')
MALFORMED_CASES = ('leaf-symlink-inside', 'leaf-symlink-outside', 'dangling-leaf-link', 'directory-leaf',
                   'modeled-special-file', 'growth-before-open', 'growth-during-read',
                   'replacement-before-open', 'replacement-during-read', 'vanished-before-open',
                   'modeled-name-replacement-after-read')
COMPATIBILITY_CASES = ('resolve-scope-noncentral-paths', 'resolve-scope-central-paths',
                       'sc75-config-outside-root-refused', 'sc13a-in-root-ancestor-alias-preserved',
                       'held-result-matches-legacy-for-accepted-inputs', 'require-noncentral-unchanged',
                       'central-replacement-refused')
ISOLATION_CASES = ('staged-module-origin', 'temporary-root-admitted', 'module-import-has-no-side-effects',
                   'peer-and-ambient-state-restored', 'finalization-complete-positive',
                   'finalization-missing-log', 'finalization-mutated-log', 'finalization-late-append')
NEGATIVE_CASES = ('legacy-leaf-alias-mutant-detected', 'restored-real-reader-positive')
SUBTEST_CASES = {
    'test_positive_contract': POSITIVE_CASES,
    'test_rejects_malformed': MALFORMED_CASES,
    'test_baseline_compatibility': COMPATIBILITY_CASES,
    'test_isolation_and_discovery': ISOLATION_CASES,
    'test_deciding_negative_control': NEGATIVE_CASES,
}
PEER_TEST = 'tests.unit.test_check_repository.ScopeTests.test_fixtures_plan_and_advisor_runbooks_are_scanned'
# Filled by test_deciding_negative_control; the runner binds it into its receipt.
NEGATIVE_EVIDENCE = []


class Product:
    """The complete, genuine product modules used by these tests."""


def staged_product():
    """Import the product from this checkout's src/ (not another editable install).

    When skippercast is not yet imported, src/ is prepended only for these imports
    (a reversible patch, restored immediately); CI's editable install already is
    the checkout. A module from any other tree fails the test loudly.
    """
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, 'dont_write_bytecode', True))
        if 'skippercast' not in sys.modules:
            stack.enter_context(mock.patch.object(sys, 'path', [str(SRC)] + sys.path))
        from skippercast.platform import contracts
        from skippercast.seafloor import scope_paths, scoped, screen
        from skippercast.util import hashing
    product = Product()
    product.contracts, product.scope_paths = contracts, scope_paths
    product.scoped, product.screen, product.hashing = scoped, screen, hashing
    for module in (contracts, scope_paths, scoped, screen, hashing):
        if not Path(module.__file__).resolve().is_relative_to(SRC.resolve()):
            raise RuntimeError(f'{module.__name__} was imported from outside this checkout')
    return product


def temporary_base():
    """The admitted parent for fixture roots (None means the inherited temporary directory)."""
    configured = os.environ.get(OUT_ENV, '').strip()
    if configured:
        base = Path(configured)
    elif (REPO.parent / 'SOURCE-MANIFEST.json').is_file():
        base = REPO.parent / 'out' / 'discovery'
    else:
        return None
    base.mkdir(parents=True, exist_ok=True)
    return base


def identity(path):
    info = os.stat(path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), info.st_size, info.st_mtime_ns, info.st_ino


def tree_state(root, exclude=()):
    """Every entry under root by lstat identity, without following links."""
    excluded = {os.fspath(item) for item in exclude}
    state = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = os.path.join(directory, name)
            if path in excluded:
                continue
            info = os.lstat(path)
            state[os.path.relpath(path, root)] = (stat.S_IFMT(info.st_mode), info.st_size,
                                                  info.st_mtime_ns, info.st_ino)
    return state


def held_state(product, digest=None):
    state = {'version': product.screen.VERSION, 'status': 'held',
             'reasons': ['scope-screen-contract-unavailable'], 'layers': [], 'scope_id': SCOPE_ID}
    if digest is not None:
        state['snapshot_sha256'] = digest
    return state


def legacy_reader(hashing):
    """Test-local copy of the 8a805820 semantics: is_file() then a path-following hash."""
    def legacy_snapshot_sha256(snapshot):
        snapshot = Path(snapshot)
        return hashing.sha256_file(snapshot) if snapshot.is_file() else None
    return legacy_snapshot_sha256


def legacy_held_state(product, root, scope_config):
    """Independent oracle for previously accepted inputs, using the genuine resolve_scope."""
    config, paths = product.scope_paths.resolve_scope(root, scope_config=scope_config)
    state = {'version': product.screen.VERSION, 'status': 'held',
             'reasons': ['scope-screen-contract-unavailable'], 'layers': [], 'scope_id': config['id']}
    digest = legacy_reader(product.hashing)(paths.screen_dir / 'snapshot.json')
    if digest is not None:
        state['snapshot_sha256'] = digest
    return state


class Fixture:
    """A unique synthetic repository root with a committed-shape noncentral scope config."""

    def __init__(self, test):
        base = temporary_base()
        self.tmp = Path(tempfile.mkdtemp(prefix='sc158-', dir=None if base is None else str(base))).resolve()
        test.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / 'root'
        catalog = self.root / 'catalog'
        catalog.mkdir(parents=True)
        self.central_config = catalog / 'seafloor-scope.json'
        shutil.copyfile(REPO / 'catalog' / 'seafloor-scope.json', self.central_config)
        config = json.loads(self.central_config.read_text(encoding='utf-8'))
        config.update(json.loads((FIXTURES / 'scope-overrides.json').read_text(encoding='utf-8')))
        self.config_document = config
        self.config = catalog / 'sc158-scope.json'
        self.config.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        self.outside = self.tmp / 'outside'
        self.outside.mkdir()
        self.external = self.outside / 'external-sentinel.json'
        shutil.copyfile(FIXTURES / 'external-sentinel.json', self.external)
        self.external_identity = identity(self.external)
        self.scope_root = self.root / 'var' / 'seafloor' / 'scopes' / SCOPE_ID
        self.screen_dir = self.scope_root / 'screen'
        self.snapshot = self.screen_dir / 'snapshot.json'
        self.inside_target = self.screen_dir / 'other.json'
        self.snapshot_bytes = (FIXTURES / 'snapshot.json').read_bytes()

    def make_screen_dir(self):
        self.screen_dir.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, data=None):
        self.make_screen_dir()
        self.snapshot.write_bytes(self.snapshot_bytes if data is None else data)


class IoSpy:
    """Reversible spies over every descriptor/stream entry point the held reader could use."""

    def __init__(self, fixture, protected=(), *, before_open=None, after_read=None, lstat_override=None):
        self.fixture = fixture
        self.protected = {Path(os.path.abspath(p)) for p in protected}
        self.before_open, self.after_read, self.lstat_override = before_open, after_read, lstat_override
        self.opened, self.closed, self.streams, self.read_sizes = [], [], [], []
        self.real_os_open, self.real_close, self.real_read = os.open, os.close, os.read
        self.real_io_open, self.real_lstat = io.open, os.lstat
        self._hooks_fired = set()
        self._stack = None

    def is_snapshot(self, path):
        return (isinstance(path, (str, bytes, os.PathLike))
                and os.path.abspath(os.fsdecode(path)) == os.fspath(self.fixture.snapshot))

    def _fire(self, name, hook):
        if hook is not None and name not in self._hooks_fired:
            self._hooks_fired.add(name)
            hook(self)

    def __enter__(self):
        def spy_open(path, flags, mode=0o777, *, dir_fd=None):
            if self.is_snapshot(path):
                self._fire('before_open', self.before_open)
            descriptor = self.real_os_open(path, flags, mode, dir_fd=dir_fd)
            self.opened.append((os.fsdecode(path), flags, descriptor))
            return descriptor

        def spy_read(descriptor, size):
            self.read_sizes.append(size)
            data = self.real_read(descriptor, size)
            if data:
                self._fire('after_read', self.after_read)
            return data

        def spy_close(descriptor):
            self.closed.append(descriptor)
            return self.real_close(descriptor)

        def spy_io_open(file, mode='r', *args, **kwargs):
            self.streams.append((file if isinstance(file, int) else os.fsdecode(file), mode))
            return self.real_io_open(file, mode, *args, **kwargs)

        def spy_lstat(path, *args, **kwargs):
            result = self.real_lstat(path, *args, **kwargs)
            if self.lstat_override is not None and self.is_snapshot(path):
                return self.lstat_override(result)
            return result

        self._stack = ExitStack()
        for owner, name, value in ((os, 'open', spy_open), (os, 'read', spy_read), (os, 'close', spy_close),
                                   (io, 'open', spy_io_open), (builtins, 'open', spy_io_open),
                                   (os, 'lstat', spy_lstat)):
            self._stack.enter_context(mock.patch.object(owner, name, value))
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False

    # Synthetic race models: they use the real primitives, so they are never recorded as reader activity.
    def append_to_snapshot(self, data=b'\n{"grown": true}\n'):
        descriptor = self.real_os_open(os.fspath(self.fixture.snapshot), os.O_WRONLY | os.O_APPEND)
        try:
            os.write(descriptor, data)
        finally:
            self.real_close(descriptor)

    def replace_snapshot(self, data=b'{"replacement": true}\n'):
        replacement = self.fixture.outside / 'replacement.json'
        descriptor = self.real_os_open(os.fspath(replacement), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.write(descriptor, data)
        finally:
            self.real_close(descriptor)
        os.replace(replacement, self.fixture.snapshot)

    def remove_snapshot(self):
        os.unlink(self.fixture.snapshot)

    def snapshot_opens(self):
        return ([entry for entry in self.opened if self.is_snapshot(entry[0])]
                + [entry for entry in self.streams if self.is_snapshot(entry[0])])

    def target_reads(self):
        hits = []
        for entry in self.opened + self.streams:
            if isinstance(entry[0], int):
                continue
            path = entry[0]
            if {Path(os.path.abspath(path)), Path(os.path.realpath(path))} & self.protected:
                hits.append(entry)
        return hits

    def write_attempts(self):
        return ([entry for entry in self.opened if entry[1] & WRITE_FLAGS]
                + [entry for entry in self.streams if any(mark in entry[1] for mark in 'wax+')])

    def unclosed(self):
        return [entry for entry in self.opened if entry[2] not in self.closed]


def modeled_fifo(result):
    """A stat seam that models a FIFO leaf; no FIFO is ever created or opened."""
    values = list(result[:10])
    values[0] = stat.S_IFIFO | 0o600
    return os.stat_result(values)


class SnapshotDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.product = staged_product()
        self.fixture = Fixture(self)
        self.enterContext(mock.patch.object(self.product.contracts, 'REPO', self.fixture.root))

    def load(self, fixture, scope_config=None, now=None):
        return self.product.scoped.load_snapshot(
            fixture.root, REACH, now, scope_config=fixture.config if scope_config is None else scope_config)

    def assert_safe_refusal(self, fixture, *, protected=(), static=True, spy_out=None,
                            reason='not a regular file', **hooks):
        """The deciding regression assertion: refuse before reading or labeling other bytes."""
        # A race model mutates the snapshot entry itself (and so its directory's mtime); all else must hold.
        excluded = () if static else (fixture.snapshot, fixture.screen_dir)
        tree_before = tree_state(fixture.root, exclude=excluded)
        with IoSpy(fixture, protected, **hooks) as spy:
            if spy_out is not None:
                spy_out.append(spy)
            with self.assertRaises(ValueError) as caught:
                self.load(fixture)
        self.assertIn(UNSAFE, str(caught.exception))
        self.assertIn(reason, str(caught.exception))
        self.assertEqual(spy.target_reads(), [], 'target-read sentinel tripped')
        self.assertEqual(spy.write_attempts(), [], 'held diagnostic attempted a write')
        self.assertEqual(spy.unclosed(), [], 'held diagnostic leaked a descriptor')
        self.assertEqual(identity(fixture.external), fixture.external_identity)
        self.assertEqual(tree_state(fixture.root, exclude=excluded), tree_before)
        if static:
            self.assertEqual(spy.snapshot_opens(), [], 'unsafe leaf was opened before refusal')
        return spy

    def test_positive_contract(self):
        product = self.product
        with self.subTest(case='absent-snapshot'):
            fx = Fixture(self)
            fx.make_screen_dir()
            with IoSpy(fx) as spy:
                state = self.load(fx)
            self.assertEqual(state, held_state(product))
            self.assertNotIn('snapshot_sha256', state)
            self.assertEqual(spy.snapshot_opens(), [])
            self.assertEqual(spy.write_attempts(), [])
        with self.subTest(case='absent-screen-dir'):
            fx = Fixture(self)
            with IoSpy(fx) as spy:
                state = self.load(fx)
            self.assertEqual(state, held_state(product))
            self.assertFalse(fx.screen_dir.exists())
            self.assertEqual(spy.write_attempts(), [])
        with self.subTest(case='tiny-regular-snapshot'):
            fx = Fixture(self)
            fx.write_snapshot()
            expected = hashlib.sha256(fx.snapshot_bytes).hexdigest()
            tree_before = tree_state(fx.root)
            with IoSpy(fx) as spy:
                state = self.load(fx)
            self.assertEqual(state, held_state(product, expected))
            self.assertEqual(state['status'], 'held')
            self.assertEqual(state['reasons'], ['scope-screen-contract-unavailable'])
            opens = [entry for entry in spy.opened if spy.is_snapshot(entry[0])]
            self.assertEqual(len(opens), 1, 'expected exactly one snapshot descriptor')
            self.assertTrue(opens[0][1] & os.O_NOFOLLOW, 'snapshot descriptor must be opened no-follow')
            self.assertEqual([entry for entry in spy.streams if spy.is_snapshot(entry[0])], [])
            self.assertEqual(spy.unclosed(), [])
            self.assertEqual(spy.write_attempts(), [])
            self.assertEqual(tree_state(fx.root), tree_before)
        with self.subTest(case='streamed-multi-chunk-snapshot'):
            fx = Fixture(self)
            data = bytes(range(256)) * 8192 + b'sc158-tail' * 52429
            fx.write_snapshot(data)
            with IoSpy(fx) as spy:
                state = self.load(fx)
            self.assertEqual(state, held_state(product, hashlib.sha256(data).hexdigest()))
            self.assertGreaterEqual(len(spy.read_sizes), 3, 'hash must stream in bounded chunks')
            self.assertLessEqual(max(spy.read_sizes), CHUNK_LIMIT)
            self.assertEqual(spy.unclosed(), [])
        for case, selected in (('central-default-delegates', None), ('central-config-delegates', 'central')):
            with self.subTest(case=case):
                fx = Fixture(self)
                central_screen = fx.root / 'var' / 'seafloor' / 'screen'
                central_screen.mkdir(parents=True)
                (central_screen / 'snapshot.json').symlink_to(fx.external)
                sentinel = object()
                scope_config = None if selected is None else fx.central_config
                with mock.patch.object(product.screen, 'load_snapshot', return_value=sentinel) as screen_sentinel, \
                     mock.patch.object(product.scoped, '_snapshot_sha256', create=True,
                                       side_effect=AssertionError('central entered the held reader')) as reader, \
                     IoSpy(fx, [fx.external]) as spy:
                    result = product.scoped.load_snapshot(fx.root, REACH, NOW, scope_config=scope_config)
                self.assertIs(result, sentinel)
                screen_sentinel.assert_called_once_with(fx.root, REACH, NOW)
                reader.assert_not_called()
                self.assertEqual(spy.target_reads(), [])

    def test_rejects_malformed(self):
        with self.subTest(case='leaf-symlink-inside'):
            fx = Fixture(self)
            fx.make_screen_dir()
            fx.inside_target.write_bytes(fx.snapshot_bytes)
            fx.snapshot.symlink_to('other.json')
            self.assert_safe_refusal(fx, protected=[fx.inside_target])
        with self.subTest(case='leaf-symlink-outside'):
            fx = Fixture(self)
            fx.make_screen_dir()
            fx.snapshot.symlink_to(fx.external)
            self.assert_safe_refusal(fx, protected=[fx.external])
        with self.subTest(case='dangling-leaf-link'):
            fx = Fixture(self)
            fx.make_screen_dir()
            fx.snapshot.symlink_to(fx.screen_dir / 'missing.json')
            self.assert_safe_refusal(fx, protected=[fx.screen_dir / 'missing.json'])
        with self.subTest(case='directory-leaf'):
            fx = Fixture(self)
            fx.snapshot.mkdir(parents=True)
            (fx.snapshot / 'inner.json').write_bytes(fx.snapshot_bytes)
            self.assert_safe_refusal(fx, protected=[fx.snapshot / 'inner.json'])
        with self.subTest(case='modeled-special-file'):
            fx = Fixture(self)
            fx.write_snapshot()
            self.assert_safe_refusal(fx, protected=[fx.external], lstat_override=modeled_fifo)
        race_models = (
            ('growth-before-open', 'before_open', IoSpy.append_to_snapshot, 'changed before it was read'),
            ('growth-during-read', 'after_read', IoSpy.append_to_snapshot, 'grew while it was read'),
            ('replacement-before-open', 'before_open', IoSpy.replace_snapshot, 'changed before it was read'),
            ('replacement-during-read', 'after_read', IoSpy.replace_snapshot, 'changed while it was read'),
            ('vanished-before-open', 'before_open', IoSpy.remove_snapshot, 'changed before it was opened'),
        )
        for case, moment, model, reason in race_models:
            with self.subTest(case=case):
                fx = Fixture(self)
                fx.write_snapshot()
                spy = self.assert_safe_refusal(fx, protected=[fx.external], static=False, reason=reason,
                                               **{moment: model})
                self.assertIn(moment, spy._hooks_fired, 'race model never reached the descriptor reader')
                opened = [entry for entry in spy.opened if spy.is_snapshot(entry[0])]
                self.assertLessEqual(len(opened), 1)
                for entry in opened:
                    self.assertIn(entry[2], spy.closed)
        with self.subTest(case='modeled-name-replacement-after-read'):
            fx = Fixture(self)
            fx.write_snapshot()
            calls = []

            def second_lstat_names_another_file(result):
                calls.append(result)
                if len(calls) < 2:
                    return result
                values = list(result[:10])
                values[1] = result.st_ino + 1
                return os.stat_result(values)

            spy = self.assert_safe_refusal(fx, protected=[fx.external], static=False,
                                           reason='name was replaced while it was read',
                                           lstat_override=second_lstat_names_another_file)
            self.assertEqual(len(calls), 2)
            self.assertEqual(len([entry for entry in spy.opened if spy.is_snapshot(entry[0])]), 1)

    def test_baseline_compatibility(self):
        product = self.product
        resolve_scope = product.scope_paths.resolve_scope
        with self.subTest(case='resolve-scope-noncentral-paths'):
            fx = Fixture(self)
            config, paths = resolve_scope(fx.root, scope_config=fx.config)
            self.assertEqual(config, fx.config_document)
            self.assertFalse(paths.is_central_default)
            self.assertEqual(paths.screen_dir, fx.screen_dir)
            self.assertEqual(paths.ledger_path, fx.scope_root / 'seafloor-ledger.json')
        with self.subTest(case='resolve-scope-central-paths'):
            fx = Fixture(self)
            config, paths = resolve_scope(fx.root, scope_config=fx.central_config)
            self.assertEqual(config['id'], 'central-coast')
            self.assertTrue(paths.is_central_default)
            self.assertEqual(paths.screen_dir, fx.root / 'var' / 'seafloor' / 'screen')
        with self.subTest(case='sc75-config-outside-root-refused'):
            fx = Fixture(self)
            outside_config = fx.outside / 'sc158-scope.json'
            shutil.copyfile(fx.config, outside_config)
            with self.assertRaisesRegex(ValueError, 'inside the repository root'):
                resolve_scope(fx.root, scope_config=outside_config)
            with IoSpy(fx, [outside_config]) as spy, \
                 self.assertRaisesRegex(ValueError, 'inside the repository root'):
                self.load(fx, scope_config=outside_config)
            self.assertEqual(spy.target_reads(), [])
            self.assertEqual(spy.snapshot_opens(), [])
        with self.subTest(case='sc13a-in-root-ancestor-alias-preserved'):
            fx = Fixture(self)
            aliased = fx.root / 'aliased-scope'
            (aliased / 'screen').mkdir(parents=True)
            (aliased / 'screen' / 'snapshot.json').write_bytes(fx.snapshot_bytes)
            fx.scope_root.parent.mkdir(parents=True)
            fx.scope_root.symlink_to(aliased, target_is_directory=True)
            _, paths = resolve_scope(fx.root, scope_config=fx.config)
            self.assertEqual(paths.screen_dir, fx.screen_dir)
            state = self.load(fx)
            self.assertEqual(state, held_state(product, hashlib.sha256(fx.snapshot_bytes).hexdigest()))
            self.assertEqual(state, legacy_held_state(product, fx.root, fx.config))
        with self.subTest(case='held-result-matches-legacy-for-accepted-inputs'):
            fx = Fixture(self)
            self.assertEqual(self.load(fx), legacy_held_state(product, fx.root, fx.config))
            fx.make_screen_dir()
            self.assertEqual(self.load(fx), legacy_held_state(product, fx.root, fx.config))
            fx.write_snapshot()
            self.assertEqual(self.load(fx, now=NOW), legacy_held_state(product, fx.root, fx.config))
        with self.subTest(case='require-noncentral-unchanged'):
            fx = Fixture(self)
            with self.assertRaisesRegex(ValueError, 'must be selected explicitly'):
                product.scoped.require_noncentral(fx.root, None)
            with self.assertRaisesRegex(ValueError, 'Central scope must use'):
                product.scoped.require_noncentral(fx.root, fx.central_config)
            config, paths = product.scoped.require_noncentral(fx.root, fx.config)
            self.assertEqual(config['id'], SCOPE_ID)
            self.assertFalse(paths.is_central_default)
        with self.subTest(case='central-replacement-refused'):
            fx = Fixture(self)
            impostor = fx.root / 'catalog' / 'impostor-central.json'
            impostor.write_text(json.dumps(dict(fx.config_document, id='central-coast')), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'cannot be replaced'):
                self.load(fx, scope_config=impostor)

    def test_isolation_and_discovery(self):
        product = self.product
        with self.subTest(case='staged-module-origin'):
            for name, module in list(sys.modules.items()):
                if name == 'skippercast' or name.startswith('skippercast.'):
                    origin = getattr(module, '__file__', None)
                    if origin is not None:
                        self.assertTrue(Path(origin).resolve().is_relative_to(SRC.resolve()), name)
            self.assertTrue(callable(product.scoped.__dict__.get('_snapshot_sha256')))
        with self.subTest(case='temporary-root-admitted'):
            base = temporary_base()
            parent = Path(tempfile.gettempdir()).resolve() if base is None else base.resolve()
            self.assertTrue(self.fixture.tmp.is_relative_to(parent))
            self.assertFalse(self.fixture.tmp.is_relative_to(REPO))
        with self.subTest(case='module-import-has-no-side-effects'):
            before = (dict(os.environ), list(sys.path), sys.dont_write_bytecode, self._sc158_entries())
            spec = importlib.util.spec_from_file_location('sc158_import_probe', Path(__file__))
            probe = importlib.util.module_from_spec(spec)
            with mock.patch.object(sys, 'dont_write_bytecode', True):
                spec.loader.exec_module(probe)
            self.assertEqual((dict(os.environ), list(sys.path), sys.dont_write_bytecode,
                              self._sc158_entries()), before)
            self.assertNotIn('sc158_import_probe', sys.modules)
            self.assertEqual(probe.REQUIRED_TESTS, REQUIRED_TESTS)
        with self.subTest(case='peer-and-ambient-state-restored'):
            peer_before = self._run_peer()
            ambient_before = self._ambient()
            entries_before = self._sc158_entries()
            inner = unittest.TestSuite([type(self)('test_positive_contract'), type(self)('test_rejects_malformed')])
            inner_result = unittest.TestResult()
            inner.run(inner_result)
            self.assertEqual((inner_result.testsRun, len(inner_result.failures), len(inner_result.errors),
                              len(inner_result.skipped)), (2, 0, 0, 0))
            self.assertEqual(self._ambient(), ambient_before)
            self.assertEqual(self._sc158_entries(), entries_before)
            self.assertEqual(self._run_peer(), peer_before)
            self.assertEqual(peer_before, (1, 0, 0, 0))
        runner = self._load_runner()
        logs = {'stdout.txt': 'synthetic stdout\n', 'stderr.txt': ''}
        receipt = {'schema': 'sc158.synthetic-finalization', 'status': 'PASS'}
        with self.subTest(case='finalization-complete-positive'):
            run_dir = self._seal_dir(runner, 'complete', receipt, logs)
            self.assertEqual(runner.verify_sealed(run_dir), [])
            with self.assertRaises(FileExistsError):
                runner.seal_run(run_dir, receipt, logs)
        with self.subTest(case='finalization-missing-log'):
            run_dir = self._seal_dir(runner, 'missing', receipt, logs)
            os.unlink(run_dir / 'stdout.txt')
            self.assertIn('missing log stdout.txt', runner.verify_sealed(run_dir))
        with self.subTest(case='finalization-mutated-log'):
            run_dir = self._seal_dir(runner, 'mutated', receipt, logs)
            (run_dir / 'stdout.txt').write_text('synthetic stdouT\n', encoding='utf-8')
            self.assertIn('changed log stdout.txt', runner.verify_sealed(run_dir))
        with self.subTest(case='finalization-late-append'):
            run_dir = self._seal_dir(runner, 'late', receipt, logs)
            with open(run_dir / 'stderr.txt', 'a', encoding='utf-8') as stream:
                stream.write('late writer\n')
            self.assertIn('changed log stderr.txt', runner.verify_sealed(run_dir))

    def test_deciding_negative_control(self):
        product = self.product
        real_reader = product.scoped.__dict__.get('_snapshot_sha256')
        self.assertTrue(callable(real_reader), 'candidate private reader seam is missing')
        with self.subTest(case='legacy-leaf-alias-mutant-detected'):
            fx = Fixture(self)
            fx.make_screen_dir()
            fx.snapshot.symlink_to(fx.external)
            spies, failure = [], None
            with mock.patch.object(product.scoped, '_snapshot_sha256', legacy_reader(product.hashing)):
                try:
                    self.assert_safe_refusal(fx, protected=[fx.external], spy_out=spies)
                except AssertionError as error:
                    failure = str(error)
            self.assertIs(product.scoped.__dict__.get('_snapshot_sha256'), real_reader)
            self.assertIsNotNone(failure, 'legacy mutant passed the deciding safe-refusal assertion')
            self.assertIn('ValueError not raised', failure)
            self.assertEqual(len(spies), 1)
            tripped = spies[0].target_reads()
            self.assertTrue(tripped, 'legacy mutant did not trip the target-read sentinel')
            self.assertEqual(identity(fx.external), fx.external_identity)
            NEGATIVE_EVIDENCE.append({'case': 'legacy-leaf-alias-mutant-detected', 'detected': True,
                                      'deciding_assertion_failure': failure,
                                      'target_reads': len(tripped)})
        with self.subTest(case='restored-real-reader-positive'):
            self.assertIs(product.scoped.__dict__.get('_snapshot_sha256'), real_reader)
            fx = Fixture(self)
            fx.write_snapshot()
            self.assertEqual(self.load(fx), held_state(product, hashlib.sha256(fx.snapshot_bytes).hexdigest()))
            fx = Fixture(self)
            fx.make_screen_dir()
            fx.snapshot.symlink_to(fx.external)
            self.assert_safe_refusal(fx, protected=[fx.external])
            NEGATIVE_EVIDENCE.append({'case': 'restored-real-reader-positive', 'passed': True})

    # Helpers for isolation checks.
    def _sc158_entries(self):
        base = temporary_base()
        parent = Path(tempfile.gettempdir()) if base is None else base
        return sorted(entry.name for entry in parent.iterdir() if entry.name.startswith('sc158-'))

    def _ambient(self):
        product = self.product
        return (list(sys.path), dict(os.environ), sys.dont_write_bytecode, tempfile.tempdir,
                os.open, os.read, os.close, os.lstat, io.open, builtins.open,
                product.contracts.REPO, product.scoped.load_snapshot,
                product.scoped.__dict__.get('_snapshot_sha256'), product.screen.load_snapshot,
                product.scope_paths.resolve_scope)

    def _run_peer(self):
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromName(PEER_TEST).run(result)
        return result.testsRun, len(result.failures), len(result.errors), len(result.skipped)

    def _load_runner(self):
        spec = importlib.util.spec_from_file_location('sc158_runner_probe', RUNNER)
        runner = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, 'dont_write_bytecode', True):
            spec.loader.exec_module(runner)
        return runner

    def _seal_dir(self, runner, name, receipt, logs):
        run_dir = self.fixture.tmp / ('seal-' + name)
        run_dir.mkdir()
        runner.seal_run(run_dir, receipt, logs)
        return run_dir


if __name__ == '__main__':
    unittest.main()

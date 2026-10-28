"""Synthetic direct-API scope checks; safe for ordinary unittest/pytest collection.

No irreversible guards or product imports at collection time. The standalone
runner owns process-wide guards. Ordinary discovery uses only scoped mocks and
fresh temporary fixtures; retained standalone evidence is never cleaned up.
"""
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests._support import FIXTURES, ROOT

FIXTURE = FIXTURES / 'sc13a-scope-output-confinement/shapes.json'
CATEGORIES = ('reference_dir', 'ledger_path', 'reaches_path', 'cells_path',
              'build_receipt_path', 'screen_dir')
DIRECTORIES = {'reference_dir', 'screen_dir'}
ERROR = 'Scope artifact path escapes repository root'
RUN_ROOT = None  # Set by the standalone caller, never by an environment flag.
PRESERVATION = []
NEGATIVE = {}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    """Snapshot without following links; entries, content and inode stay fixed."""
    entries = {}
    for path in sorted(root.rglob('*')):
        st = path.lstat()
        if path.is_symlink():
            value = ('link', os.readlink(path))
        elif path.is_dir():
            value = ('dir',)
        else:
            value = ('file', digest(path))
        entries[path.relative_to(root).as_posix()] = [st.st_ino, *value]
    return entries


def expected(root, layout):
    """Independent literal layout oracle; does not call the submitted resolver."""
    if layout == 'central':
        reference = root / 'var/seafloor/reference'
        return dict(zip(CATEGORIES, (reference, root / 'dist/data/seafloor-ledger.json',
                    root / 'catalog/reaches.json', reference / 'cells.json',
                    reference / 'run.json', root / 'var/seafloor/screen')))
    scope = root / 'var/seafloor/scopes/offline-demo'
    return dict(zip(CATEGORIES, (scope / 'reference', scope / 'seafloor-ledger.json',
                scope / 'reaches.json', scope / 'reference/cells.json',
                scope / 'reference/run.json', scope / 'screen')))


class ScopeCase(unittest.TestCase):
    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix='sc13a-', dir=RUN_ROOT))
        self.root = self.case / 'repo'
        (self.root / 'catalog').mkdir(parents=True)
        self.sibling = self.case / 'repo-sibling'
        self.sibling.mkdir()
        (self.sibling / 'sentinel.txt').write_text('unchanged synthetic sentinel\n')
        self.shapes = json.loads(FIXTURE.read_text())
        # Standalone guards redirect contracts before loading this module.
        # Ordinary tests must not bind contracts' cached defaults to a temporary
        # fixture: import normally and always pass explicit roots instead.
        self.product = importlib.import_module('skippercast.seafloor.scope_paths')

    def config(self, layout):
        value = copy.deepcopy(self.shapes[layout])
        name = 'seafloor-scope.json' if layout == 'central' else 'demo-scope.json'
        path = self.root / 'catalog' / name
        path.write_text(json.dumps(value))
        return value, path

    def resolve(self, layout, config, **kwargs):
        if layout == 'noncentral':
            kwargs.setdefault('scope_config', config)
        root = kwargs.pop('root', self.root)
        before = snapshot(self.case)
        opened = []
        original = io.open

        def watch(file, *args, **kw):
            if not isinstance(file, int):
                resolved = Path(file).resolve()
                opened.append(str(resolved))
                self.assertEqual(resolved, config.resolve(), 'resolver opened non-config target bytes')
            return original(file, *args, **kw)

        try:
            with patch.object(io, 'open', side_effect=watch):
                return self.product.resolve_scope(root, **kwargs)
        finally:
            after = snapshot(self.case)
            self.assertEqual(before, after, 'resolver mutated synthetic inputs/entries/outputs')
            PRESERVATION.append({'test': self.id(), 'case': str(self.case),
                                 'before': before, 'after': after, 'opened': opened})

    def assert_valid(self, layout, config, value, **kwargs):
        loaded, paths = self.resolve(layout, config, **kwargs)
        self.assertEqual(loaded, value)
        self.assertEqual(paths.scope_id, value['id'])
        self.assertEqual(paths.config_path, config.resolve())
        self.assertEqual(paths.is_central_default, layout == 'central')
        for category, path in expected(self.root, layout).items():
            self.assertEqual(getattr(paths, category), path, category)
            self.assertTrue(path.resolve().is_relative_to(self.root.resolve()), category)
        return paths

    def assert_escape(self, layout, config):
        with self.assertRaisesRegex(ValueError, ERROR):
            self.resolve(layout, config)

    def link(self, path, category, state, *, internal=False):
        base = self.root / 'inside-targets' if internal else self.sibling
        base.mkdir(exist_ok=True)
        target = base / 'target'
        if state == 'existing':
            if category in DIRECTORIES or category == 'ancestor':
                target.mkdir()
                (target / 'sentinel.txt').write_text('directory sentinel\n')
            else:
                target.write_text('file sentinel\n')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Relative targets additionally exercise non-absolute link resolution.
        path.symlink_to(os.path.relpath(target, path.parent),
                        target_is_directory=category in DIRECTORIES or category == 'ancestor')


class ScopeRegression(ScopeCase):
    def test_root_alias(self):
        value, config = self.config('central')
        alias = self.case / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        self.assert_valid('central', config, value, root=alias)
        self.assert_valid('central', config, value,
                          root=Path(os.path.relpath(self.root, Path.cwd())))


def positive(layout, state):
    def test(self):
        value, config = self.config(layout)
        if state == 'ordinary':
            for category, path in expected(self.root, layout).items():
                path.parent.mkdir(parents=True, exist_ok=True)
                if category in DIRECTORIES:
                    path.mkdir(exist_ok=True)
                else:
                    path.write_text('existing output sentinel\n')
        self.assert_valid(layout, config, value)
        if state == 'absent':
            self.assertFalse((self.root / 'var').exists())
            self.assertFalse((self.root / 'dist').exists())
    return test


def linked(layout, category, state, internal):
    def test(self):
        value, config = self.config(layout)
        self.link(expected(self.root, layout)[category], category, state, internal=internal)
        if internal:
            self.assert_valid(layout, config, value)
        else:
            self.assert_escape(layout, config)
    return test


ANCESTORS = {
    'central_var': ('central', 'var'),
    'central_dist': ('central', 'dist'),
    'central_reference': ('central', 'var/seafloor/reference'),
    'noncentral_var': ('noncentral', 'var'),
    'noncentral_scopes': ('noncentral', 'var/seafloor/scopes'),
    'noncentral_id': ('noncentral', 'var/seafloor/scopes/offline-demo'),
}


def ancestor(layout, relative, state):
    def test(self):
        _, config = self.config(layout)
        self.link(self.root / relative, 'ancestor', state)
        self.assert_escape(layout, config)
    return test


for _layout in ('central', 'noncentral'):
    for _state in ('absent', 'ordinary'):
        setattr(ScopeRegression, f'test_{_state}_{_layout}', positive(_layout, _state))
    for _category in CATEGORIES:
        for _state in ('existing', 'dangling'):
            for _internal in (False, True):
                _label = 'inroot' if _internal else 'escape'
                setattr(ScopeRegression, f'test_{_label}_{_layout}_{_category}_{_state}',
                        linked(_layout, _category, _state, _internal))
for _name, (_layout, _relative) in ANCESTORS.items():
    for _state in ('existing', 'dangling'):
        setattr(ScopeRegression, f'test_ancestor_{_name}_{_state}', ancestor(_layout, _relative, _state))


class ScopeCompatibility(ScopeCase):
    def test_explicit_central(self):
        value, config = self.config('central')
        self.assert_valid('central', config, value, scope_config=config, scope_id='central-coast')

    def test_relative_noncentral_config(self):
        value, config = self.config('noncentral')
        self.assert_valid('noncentral', config, value,
                          scope_config=config.relative_to(self.root), scope_id='offline-demo')

    def test_invalid_ids(self):
        value, config = self.config('noncentral')
        for ident in (None, True, 1, '', 'Upper', '../outside', 'under_score', 'two--hyphens'):
            with self.subTest(ident=ident):
                config.write_text(json.dumps(dict(value, id=ident)))
                with self.assertRaisesRegex(ValueError, 'stable lowercase ID'):
                    self.resolve('noncentral', config)
        del value['id']
        config.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'stable lowercase ID'):
            self.resolve('noncentral', config)

    def test_missing_and_mismatch(self):
        missing = self.root / 'catalog/demo-scope.json'
        with self.assertRaises(FileNotFoundError):
            self.resolve('noncentral', missing)
        value, config = self.config('noncentral')
        with self.assertRaisesRegex(ValueError, 'requires an explicit scope config'):
            self.resolve('central', config, scope_id=value['id'])
        with self.assertRaisesRegex(ValueError, 'Requested scope ID does not match'):
            self.resolve('noncentral', config, scope_id='other-demo')

    def test_central_identity(self):
        value, config = self.config('noncentral')
        config.write_text(json.dumps(dict(value, id='central-coast')))
        with self.assertRaisesRegex(ValueError, 'central scope config cannot be replaced'):
            self.resolve('noncentral', config)
        _, canonical = self.config('central')
        canonical.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'must be selected explicitly'):
            self.resolve('central', canonical)

    def test_explicit_config_confinement(self):
        _, config = self.config('noncentral')
        outside = self.sibling / 'config.json'
        outside.write_text(json.dumps(self.shapes['noncentral']))
        with self.assertRaisesRegex(ValueError, 'Scope config must be inside'):
            self.resolve('noncentral', config, scope_config=outside)
        alias = self.root / 'catalog/alias.json'
        alias.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'Scope config must be inside'):
            self.resolve('noncentral', config, scope_config=alias)

    def test_json_contract(self):
        _, config = self.config('noncentral')
        for text, reason in (('{"id":"offline-demo","id":"other"}', 'Duplicate JSON key'),
                             ('{"id":"offline-demo","value":NaN}', 'Non-finite JSON number'),
                             ('{', 'Expecting property name')):
            with self.subTest(text=text):
                config.write_text(text)
                with self.assertRaisesRegex(ValueError, reason):
                    self.resolve('noncentral', config)

    def test_peer_isolation(self):
        from skippercast import paths
        original = paths.repo_root
        environment = dict(os.environ)
        value, config = self.config('noncentral')
        with patch.object(paths, 'repo_root', return_value=self.root):
            self.assert_valid('noncentral', config, value)
        self.assertIs(paths.repo_root, original)
        # Exercise standard collection of this exact file (not peer suites).
        # Discovery's own temporary sys.path addition is scoped and restored.
        path_before = sys.path
        with patch.object(sys, 'path', list(sys.path)):
            collected = unittest.TestLoader().discover(
                str(ROOT / 'tests/gis'), pattern='test_sc13a_scope_output_confinement.py')
            self.assertGreater(collected.countTestCases(), 0)
            self.assertIsNone(sys.modules['test_sc13a_scope_output_confinement'].RUN_ROOT)
        self.assertIs(sys.path, path_before)
        ordinary = unittest.defaultTestLoader.loadTestsFromName(
            'tests.gis.test_sc13a_scope_output_confinement')
        self.assertGreater(ordinary.countTestCases(), 0)
        self.assertIs(paths.repo_root, original)
        self.assertEqual(dict(os.environ), environment)
        # This module adds no audit hook or process/network monkeypatch at all.


class ScopePreflight(ScopeCase):
    def test_import_fixture_closure(self):
        value, config = self.config('central')
        self.assertEqual(value['schema_version'], 1)
        self.assertEqual(value['regions'][0]['id'], 'demo-region')
        self.assert_valid('central', config, value)
        from skippercast.platform import contracts
        if RUN_ROOT is not None:
            self.assertTrue(contracts.REPO.is_relative_to(Path(RUN_ROOT).parent))
            self.assertEqual(contracts.load_catalogs.__defaults__[0], contracts.REPO)
            self.assertEqual(contracts.load_region.__defaults__[0], contracts.REPO)
        self.assertEqual(Path(self.product.__file__).resolve(),
                         ROOT / 'src/skippercast/seafloor/scope_paths.py')


class ScopeNegativeControl(ScopeCase):
    def test_old_resolver_detected(self):
        value, config = self.config('central')
        self.assert_valid('central', config, value)
        self.link(self.root / 'var', 'ancestor', 'existing')
        with patch.object(self.product, '_sc13a_require_artifact_paths', return_value=None):
            # This one no-op restores the exact old output-path construction;
            # config parsing/identity checks and all unrelated gates stay real.
            with self.assertRaises(AssertionError) as caught:
                self.assert_escape('central', config)
            inner = str(caught.exception)
            self.assertIn('ValueError not raised', inner)
            loaded, paths = self.resolve('central', config)
            self.assertEqual(loaded, value)
            self.assertFalse(paths.reference_dir.resolve().is_relative_to(self.root))
            # A second ordinary scope is positive with the mutant enabled.
            other = ScopeRegression('test_absent_central')
            result = unittest.TestResult()
            other.run(result)
            self.assertTrue(result.wasSuccessful(), str(result.errors + result.failures))
        self.assert_escape('central', config)
        other = ScopeRegression('test_absent_central')
        result = unittest.TestResult()
        other.run(result)
        self.assertTrue(result.wasSuccessful(), str(result.errors + result.failures))
        NEGATIVE.update(mutant_detected=True, positive_passed=True,
                        inner_failure=inner, restored_escape_rejected=True)

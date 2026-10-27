"""SC178 offline complete-API species fit typing checks for screen_candidates.

Safe under ordinary unittest discovery: no product imports, fixtures, process-wide
hooks or environment edits at import time. Each method allocates a new synthetic
root (CI-owned temp root or the runner's invocation child) and retains it.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import importlib
import importlib.abc
import importlib.util
import inspect
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests._support import ROOT as REPO
FIXTURES = REPO / 'tests/fixtures/sc178-species-fit-types'
METHODS = ('test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation')
HELD = 'habitat-contract-incomplete'


class OfflineViolation(RuntimeError):
    """Unexpected external effect: never an expected product refusal."""


EFFECTS = []
DEPENDENCY_ENV = []


def forbidden(*args, **kwargs):
    EFFECTS.append(repr(args[:1]))
    raise OfflineViolation('SC178 STOP: external effect prohibited')


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm', 'transformers'}:
            raise OfflineViolation('SC178 STOP: model import prohibited')
        return None


def ambient_state():
    # six (and botocore's vendored copy), pulled in by the survey stack, appends its
    # importer to sys.meta_path on first import; that one-time library side effect is
    # not a test leak, so it is excluded, which keeps the check order-independent.
    meta_path = tuple(f for f in sys.meta_path if type(f).__name__ != '_SixMetaPathImporter')
    return (dict(os.environ), tuple(sys.path), meta_path, sys.dont_write_bytecode,
            socket.getaddrinfo, socket.create_connection, socket.socket.connect,
            subprocess.Popen, os.system, io.open)


def legacy_fit(fit):
    """Baseline membership predicate (admits True and equal floats); reversible seam only."""
    return bool(fit) and all(v in (1, 2, 3) for v in fit.values())


@contextmanager
def offline_product(root):
    """Inspected closure only; reversible sentinels, not a hostile-code sandbox.

    paths.repo_root is redirected before contracts initializes. Every loaded
    skippercast module's REPO/repo_root binding and every function default that
    equals the repository root are redirected to the synthetic root for the
    duration, then restored to the genuine repository values.
    """
    before = ambient_state()
    finder = NoModels()
    rebinds = []
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
            # Installed rasterio's first import setdefaults its CA-bundle variables
            # (rasterio/_env.pyx); the environment is restored exactly on exit.
            environ_before = dict(os.environ)
            stack.enter_context(patch.dict(os.environ))
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
                    forbidden(value)

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
            genuine_root, genuine_fn = paths.repo_root(), paths.repo_root
            redirected = lambda: root  # noqa: E731
            paths.repo_root = redirected
            rebinds.append((paths, 'repo_root', genuine_fn))
            screen = importlib.import_module('skippercast.seafloor.screen')
            # Lazily imported producers used by tests are bound before redirection.
            for extra in ('habitat', 'classified_habitat', 'bedrock_habitat'):
                importlib.import_module('skippercast.seafloor.' + extra)
            for name, module in list(sys.modules.items()):
                if not name.startswith('skippercast') or module is None:
                    continue
                origin = Path(getattr(module, '__file__', '') or '/').resolve()
                if not origin.is_relative_to(REPO / 'src'):
                    raise OfflineViolation(f'SC178 STOP: {name} imported outside candidate source')
                if getattr(module, 'REPO', None) in (genuine_root, root):
                    rebinds.append((module, 'REPO', genuine_root))
                    module.REPO = root
                if getattr(module, 'repo_root', None) in (genuine_fn, redirected) and module is not paths:
                    rebinds.append((module, 'repo_root', genuine_fn))
                    module.repo_root = redirected
                for value in list(vars(module).values()):
                    if inspect.isfunction(value) and value.__module__ == name:
                        if value.__defaults__ and any(v in (genuine_root, root) for v in value.__defaults__
                                                      if isinstance(v, Path)):
                            rebinds.append((value, '__defaults__', tuple(
                                genuine_root if isinstance(v, Path) and v in (genuine_root, root) else v
                                for v in value.__defaults__)))
                            value.__defaults__ = tuple(root if isinstance(v, Path) and v == genuine_root else v
                                                       for v in value.__defaults__)
                        kw = value.__kwdefaults__
                        if kw and any(isinstance(v, Path) and v in (genuine_root, root) for v in kw.values()):
                            rebinds.append((value, '__kwdefaults__', {
                                k: genuine_root if isinstance(v, Path) and v in (genuine_root, root) else v
                                for k, v in kw.items()}))
                            value.__kwdefaults__ = {k: root if isinstance(v, Path) and v == genuine_root else v
                                                    for k, v in kw.items()}
            http = sys.modules.get('skippercast.http')
            if http is not None:
                stack.enter_context(patch.object(http, 'default_session', forbidden))
            if Path(screen.__file__).resolve() != REPO / 'src/skippercast/seafloor/screen.py':
                raise OfflineViolation('SC178 STOP: wrong product module origin')
            if sys.modules['skippercast.seafloor.search_areas'].REPO != root:
                raise OfflineViolation('SC178 STOP: unredirected product data root')
            DEPENDENCY_ENV.append(sorted(k for k in os.environ if k not in environ_before))
            if set(DEPENDENCY_ENV[-1]) - {'GDAL_CURL_CA_BUNDLE', 'PROJ_CURL_CA_BUNDLE'}:
                raise OfflineViolation('SC178 STOP: unexpected import-time environment change')
            yield screen
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for owner, name, value in reversed(rebinds):
            setattr(owner, name, value)
        if ambient_state() != before:
            raise OfflineViolation('SC178 STOP: ambient state not restored')


class SpeciesFitTypeTests(unittest.TestCase):
    output_prefix = None
    records = []
    preservation = []
    negative_control = []
    origins = {}
    fixture_hashes = []

    def setUp(self):
        # CI may supply tempfile.tempdir/TMPDIR; do not override that ownership.
        parent = self.output_prefix or tempfile.gettempdir()
        self.root = Path(tempfile.mkdtemp(prefix='sc178-', dir=parent))
        spec = importlib.util.spec_from_file_location('sc178_constructors', FIXTURES / 'constructors.py')
        self.fx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fx)
        # Synthetic data root: only the reviewed rule catalog the search exemption reads.
        (self.root / 'catalog').mkdir()
        shutil.copyfile(REPO / 'catalog/habitat-rules.json', self.root / 'catalog/habitat-rules.json')
        type(self).fixture_hashes.append({
            'constructors': self.fx.digest(FIXTURES / 'constructors.py'),
            'habitat_rules': self.fx.digest(self.root / 'catalog/habitat-rules.json'),
            'root': str(self.root)})
        del EFFECTS[:]
        self.guards = offline_product(self.root)
        self.screen = self.guards.__enter__()
        self.addCleanup(self.guards.__exit__, None, None, None)
        self.rules = sys.modules['skippercast.platform.contracts'].read_json(
            self.root / 'catalog/habitat-rules.json')
        for name, module in list(sys.modules.items()):
            if name.startswith('skippercast') and getattr(module, '__file__', None):
                type(self).origins[name] = str(Path(module.__file__).resolve())

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

    def run_screen(self, features, state=None):
        return self.screen.screen_candidates({'type': 'FeatureCollection', 'features': features},
                                             state or self.fx.state())

    def assert_passed_habitat(self, feature, grade='B'):
        p = feature['properties']
        self.assertEqual((p['tier'], p['status'], p['exportable'], p['hold_reasons'], p['screen']['status']),
                         (2, 'habitat', True, [], 'pass'))
        self.assertEqual(p['terrain']['grade'], grade)
        self.assertEqual(p['label'], self.fx.EXPECTED_HABITAT_LABEL)

    def assert_held(self, feature, reasons):
        p = feature['properties']
        self.assertEqual(p['hold_reasons'], sorted(reasons))
        self.assertNotIn('habitat-geometry-invalid', p['hold_reasons'])
        self.assertEqual((p['tier'], p['status'], p['exportable'], p['screen']['status']), (1, 'held', False, 'held'))
        self.assertTrue(p['label'].startswith('Held: ' + ', '.join(sorted(reasons)) + '. '))

    def assert_held_fit(self, bad, reasons=(HELD,)):
        # Deciding assertion reused literally by regression and the legacy control.
        peers = [self.fx.candidate('peer-before', 200, 0), self.fx.candidate('peer-after', 0, 200)]
        passed, held, summary = self.run_screen([peers[0], bad, peers[1]])
        ident = bad['properties']['id']
        if any(f['properties']['id'] == ident for f in passed['features']):
            self.fail(f'malformed fit passed: {ident}')
        self.assertEqual([f['properties']['id'] for f in held['features']], [ident])
        self.assert_held(held['features'][0], reasons)
        self.assertEqual([f['properties']['id'] for f in passed['features']], ['peer-before', 'peer-after'])
        for feature in passed['features']:
            self.assert_passed_habitat(feature)
        self.assertEqual((summary['habitat_count'], summary['held_candidate_count'], summary['habitat_by_grade']),
                         (2, 1, {'B': 2}))
        self.assertEqual(summary['held_by_reason'], {r: 1 for r in reasons})
        return passed, held, summary

    def test_regression(self):
        for label in self.fx.MALFORMED:
            with self.case(label):
                self.assert_held_fit(self.fx.malformed(label))
        with self.case('search-requested-list-fit'):
            bad = self.fx.search_patch('bad-search-list', self.rules['rule_version'])
            bad['properties']['fit'] = [3]
            self.assert_held_fit(bad, (HELD, 'metric-support-incomplete'))
        with self.case('classified-requested-scalar-fit'):
            policy, row, binding = self.fx.classified_inputs()
            bad = sys.modules['skippercast.seafloor.classified_habitat'].features_for(
                [self.fx.native_box(400, 400)], 'fixture', policy, row, binding)['features'][0]
            bad['properties']['fit'] = 3
            self.assert_held_fit(bad, (HELD, 'classified-contract-incomplete', 'metric-support-incomplete'))
        with self.case('mixed-collection-all-malformed'):
            features, expected_held, expected_passed = [], [], []
            for index, label in enumerate(self.fx.MALFORMED):
                x, y = 60 * (index % 10), 60 * (index // 10)
                features.append(self.fx.malformed(label, x, y)); expected_held.append('bad-' + label)
                features.append(self.fx.candidate(f'peer-{index}', x, 700 + y)); expected_passed.append(f'peer-{index}')
            passed, held, summary = self.run_screen(features)
            self.assertEqual([f['properties']['id'] for f in held['features']], expected_held)
            self.assertEqual([f['properties']['id'] for f in passed['features']], expected_passed)
            for feature in held['features']:
                self.assert_held(feature, [HELD])
            for feature in passed['features']:
                self.assert_passed_habitat(feature)
            self.assertEqual(summary['held_by_reason'], {HELD: len(self.fx.MALFORMED)})
            self.assertEqual(summary['habitat_count'], len(self.fx.MALFORMED))

    def test_compatibility(self):
        for rank in (1, 2, 3):
            with self.case(f'int-rank-{rank}'):
                passed, held, _ = self.run_screen([self.fx.candidate(f'rank-{rank}', fit={'lingcod': rank})])
                self.assertFalse(held['features'])
                self.assert_passed_habitat(passed['features'][0])
                self.assertEqual(passed['features'][0]['properties']['fit'], {'lingcod': rank})
        with self.case('multi-species-int-ranks'):
            fit = {'lingcod': 3, 'rockfish-reef': 1}
            passed, held, _ = self.run_screen([self.fx.candidate('multi', fit=fit)])
            self.assertFalse(held['features']); self.assert_passed_habitat(passed['features'][0])
            self.assertEqual(passed['features'][0]['properties']['fit'], fit)
        with self.case('producer-species-fit-ranks'):
            habitat = importlib.import_module('skippercast.seafloor.habitat')
            features = []
            for index, (low, high, grade) in enumerate(((30, 40, 'A'), (30, 40, 'C'), (200, 210, 'B'), (5, 8, 'A'))):
                fit = {key: habitat.species_fit(low, high, grade, value) for key, value in self.rules['species'].items()}
                self.assertTrue(all(type(v) is int and v in (1, 2, 3) for v in fit.values()))
                features.append(self.fx.candidate(f'producer-{index}', 60 * index, 0, fit=fit, grade=grade))
            passed, held, summary = self.run_screen(features)
            self.assertFalse(held['features'])
            self.assertEqual([f['properties']['id'] for f in passed['features']],
                             [f['properties']['id'] for f in features])
            self.assertEqual(summary['habitat_by_grade'], {'A': 2, 'B': 1, 'C': 1})
        with self.case('summary-counts-and-grades'):
            features = [self.fx.candidate(f'g-{i}', 60 * i, 0, fit={'lingcod': 1 + i % 3}, grade='ABC'[i % 3])
                        for i in range(6)]
            passed, held, summary = self.run_screen(features)
            self.assertEqual((summary['habitat_count'], summary['held_candidate_count'], summary['habitat_by_grade'],
                              summary['search_area_count'], summary['classified_area_count'], summary['held_by_reason']),
                             (6, 0, {'A': 2, 'B': 2, 'C': 2}, 0, 0, {}))
            self.assertAlmostEqual(summary['tier2_km2'], .015, places=8)
        with self.case('input-order-and-objects'):
            features = [self.fx.candidate('z', 0, 0), self.fx.malformed('bool-true-rank', 60, 0),
                        self.fx.candidate('a', 120, 0)]
            before, objects = deepcopy(features), [id(f) for f in features]
            collection = {'type': 'FeatureCollection', 'features': features}
            passed, held, _ = self.screen.screen_candidates(collection, self.fx.state())
            self.assertEqual(features, before); self.assertEqual([id(f) for f in collection['features']], objects)
            self.assertEqual([f['properties']['id'] for f in passed['features']], ['z', 'a'])
            self.assertTrue(all(f is not g for f in passed['features'] + held['features'] for g in features))
        with self.case('search-area-exemption-unranked'):
            c = self.fx.search_patch('search', self.rules['rule_version'])
            passed, held, summary = self.run_screen([c])
            self.assertFalse(held['features'])
            p = passed['features'][0]['properties']
            self.assertEqual((p['tier'], p['status'], p['exportable'], p['fit']),
                             (1, 'search-area', False, {'lingcod': 'unknown', 'rockfish-reef': 'unknown'}))
            self.assertTrue(sys.modules['skippercast.seafloor.search_areas'].published_contract(p))
            self.assertEqual((summary['habitat_count'], summary['search_area_count'], summary['habitat_by_grade']),
                             (0, 1, {}))
        policy, row, binding = self.fx.classified_inputs()
        ch = sys.modules['skippercast.seafloor.classified_habitat']
        with self.case('classified-area-exemption-unranked'):
            c = ch.features_for([self.fx.native_box()], 'fixture', policy, row, binding)['features'][0]
            passed, held, summary = self.run_screen([c])
            self.assertFalse(held['features'])
            p = passed['features'][0]['properties']
            self.assertEqual((p['tier'], p['status'], p['exportable']), (1, 'classified-area', False))
            self.assertTrue(ch.published_contract(p))
            self.assertEqual((summary['habitat_count'], summary['classified_area_count']), (0, 1))
        overlap = self.fx.state(self.fx.geo(40, 0))
        with self.case('search-area-safety-not-bypassed'):
            _, held, _ = self.run_screen([self.fx.search_patch('search', self.rules['rule_version'])], overlap)
            self.assertIn('overlap-cdfw-mpa', held['features'][0]['properties']['hold_reasons'])
        with self.case('classified-area-safety-not-bypassed'):
            c = ch.features_for([self.fx.native_box()], 'fixture', policy, row, binding)['features'][0]
            _, held, _ = self.run_screen([c], overlap)
            self.assertIn('overlap-cdfw-mpa', held['features'][0]['properties']['hold_reasons'])
        with self.case('ranked-safety-not-bypassed'):
            passed, held, _ = self.run_screen([self.fx.candidate('ranked')], overlap)
            self.assertFalse(passed['features'])
            self.assertEqual(held['features'][0]['properties']['hold_reasons'],
                             ['overlap-cdfw-mpa', 'overlap-noaa-federal', 'overlap-security'])
        with self.case('search-with-int-rank-not-exempt'):
            c = self.fx.search_patch('search-ranked', self.rules['rule_version'])
            c['properties']['fit'] = {'lingcod': 3}
            passed, held, _ = self.run_screen([c])
            self.assertFalse(passed['features'])
            self.assertEqual(held['features'][0]['properties']['hold_reasons'], ['metric-support-incomplete'])
        with self.case('existing-held-shapes-unchanged'):
            for change, reasons in (({'terrain': 'unknown'}, ['metric-support-incomplete']),
                                    ({'depth_max_ft': 301}, [HELD]),
                                    ({'fit': {'lingcod': 'unknown'}}, [HELD]),
                                    ({'resolution_m': None}, None)):
                c = self.fx.candidate('changed'); c['properties'].update(change)
                if reasons is None:
                    # Missing resolution keeps its existing geometry-invalid hold.
                    del c['properties']['resolution_m']
                    reasons = ['habitat-geometry-invalid']
                passed, held, _ = self.run_screen([c])
                self.assertFalse(passed['features'])
                self.assertEqual(held['features'][0]['properties']['hold_reasons'], reasons)

    def test_negative_control(self):
        bad = self.fx.malformed('bool-true-rank')
        with self.case('legacy-bool-predicate-detected'):
            with patch.object(self.screen, '_ranked_fit', legacy_fit):
                with self.assertRaisesRegex(AssertionError, 'malformed fit passed') as caught:
                    self.assert_held_fit(deepcopy(bad))
            type(self).negative_control.append({'detected': True, 'inner_assertion': str(caught.exception),
                                                'predicate': 'legacy_fit', 'fit': {'lingcod': True}})
        with self.case('restored-bool-held'):
            self.assertIsNot(self.screen._ranked_fit, legacy_fit)
            self.assert_held_fit(deepcopy(bad))
        with self.case('restored-integer-positive'):
            passed, held, _ = self.run_screen([self.fx.candidate('positive', fit={'lingcod': 3})])
            self.assertFalse(held['features']); self.assert_passed_habitat(passed['features'][0])

    def test_preservation(self):
        features = []
        for index, label in enumerate(self.fx.MALFORMED):
            features.append(self.fx.malformed(label, 60 * (index % 10), 60 * (index // 10)))
        features.insert(5, self.fx.candidate('eligible', 0, 900))
        collection = {'type': 'FeatureCollection', 'features': features}
        state = self.fx.state()
        before_collection, before_state = deepcopy(collection), deepcopy(state)
        before_root = self.fx.snapshot(self.root)
        passed, held, _ = self.screen.screen_candidates(collection, state)
        with self.case('input-collection-unchanged'):
            self.assertEqual(collection, before_collection)
        with self.case('state-unchanged'):
            self.assertEqual(state, before_state)
        with self.case('synthetic-root-unchanged'):
            self.assertEqual(self.fx.snapshot(self.root), before_root)
        with self.case('held-rescreen-stable'):
            again_passed, again_held, _ = self.screen.screen_candidates(held, state)
            self.assertFalse(again_passed['features'])
            self.assertEqual([f['properties']['hold_reasons'] for f in again_held['features']],
                             [[HELD]] * len(self.fx.MALFORMED))
        with self.case('eligible-peer-not-suppressed'):
            self.assertEqual([f['properties']['id'] for f in passed['features']], ['eligible'])
            self.assert_passed_habitat(passed['features'][0])
            again, _, _ = self.screen.screen_candidates(passed, state)
            self.assertEqual([f['properties']['id'] for f in again['features']], ['eligible'])
        with self.case('no-external-effects'):
            self.assertEqual(EFFECTS, [])
        type(self).preservation.append({'root': str(self.root), 'before': before_root,
                                        'after': self.fx.snapshot(self.root),
                                        'input_unchanged': collection == before_collection,
                                        'state_unchanged': state == before_state})


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""SC176 full-API regression: standalone unittest discovery and inert imports."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests._support import ROOT

_FIXTURE = ROOT / 'tests/fixtures/sc176-scope-catalog-ids/constructors.py'
_spec = importlib.util.spec_from_file_location('sc176_constructors', _FIXTURE)
if _spec is None or _spec.loader is None:
    raise RuntimeError('Missing SC176 portable constructors')
fixture = importlib.util.module_from_spec(_spec)
with patch.object(sys, 'dont_write_bytecode', True):
    _spec.loader.exec_module(fixture)

REQUIRED_CASES = {
    'test_regression': [
        'identical', 'private-public', 'public-private', 'missing-id', 'empty-id',
        'null-id', 'int-id', 'bool-id', 'list-id', 'dict-id', 'surveys-missing',
        'surveys-null', 'surveys-object', 'surveys-string', 'surveys-tuple',
        'row-null', 'row-list', 'row-string', 'row-int'],
    'test_compatibility': [
        'transitive-order-audit', 'empty-inventory', 'literal-identities',
        'all-valid-identity', 'all-malformed-identity', 'configured-scope',
        'configured-weakening', 'missing-marker', 'wrong-root-marker',
        'noncommercial', 'unknown-scope', 'default-marked-root', 'rights-unchanged'],
    'test_negative_control': ['last-row-wins-detected', 'restored-duplicate-refusal',
                              'restored-unique-positive'],
    'test_preservation': ['invalid-inputs-unchanged', 'valid-inputs-unchanged',
                          'peer-state-restored'],
}


class ScopeCatalogIDsTests(unittest.TestCase):
    completed = []
    module_origins = {}
    negative_outcomes = []
    run_roots = []

    def setUp(self):
        self.root = fixture.new_root(self._testMethodName)
        self.case_results = []
        type(self).run_roots.append(str(self.root))

    def tearDown(self):
        # Normal unittest discovery also retains actual per-case execution IDs.
        receipt = {'test_id': self.id(), 'cases': self.case_results,
                   'method': self._testMethodName, 'root': str(self.root)}
        (self.root / 'method-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('SC176_METHOD ' + json.dumps(receipt, sort_keys=True))

    @contextmanager
    def case(self, name):
        entry = {'id': self.id() + ':' + name, 'case': name, 'passed': False}
        self.case_results.append(entry)
        with self.subTest(case=name):
            yield
            entry['passed'] = True
            type(self).completed.append((self._testMethodName, name))

    @contextmanager
    def product(self):
        with fixture.offline_product(self.root) as (scope, rights, origins, violations):
            type(self).module_origins.update(origins)
            yield scope, rights
            self.assertEqual(violations, [])

    def refusal(self, scope, root, manifest, observed=None):
        """Same deciding assertion for genuine and deliberately bypassed paths."""
        with patch.object(scope, 'sha256', wraps=scope.sha256) as hashing, \
                patch.object(scope, 'government_row', wraps=scope.government_row) as filtering:
            with self.assertRaises(ValueError):
                result = scope.scoped_manifest(root, manifest)
                if observed is not None:
                    observed['result'] = result
                    observed['hash_calls'] = hashing.call_count
                    observed['lineage_calls'] = filtering.call_count
            hashing.assert_not_called()
            filtering.assert_not_called()

    def test_regression(self):
        cases = fixture.invalid_cases()
        self.assertEqual(set(cases), set(REQUIRED_CASES['test_regression']))
        with self.product() as (scope, _):
            for name in REQUIRED_CASES['test_regression']:
                with self.case(name):
                    root = self.root / name
                    manifest = deepcopy(cases[name])
                    fixture.configure(root, manifest)
                    self.assertEqual(scope.processing_scope(root), 'government-only')
                    self.refusal(scope, root, manifest)

    def test_compatibility(self):
        with self.product() as (scope, rights):
            manifest = fixture.unique_catalog()
            root = self.root / 'valid'
            fixture.configure(root, manifest)
            with self.case('transitive-order-audit'):
                selected, audit = scope.scoped_manifest(root, manifest)
                self.assertEqual([r['id'] for r in selected['surveys']], ['leaf', 'middle', 'original'])
                self.assertEqual(selected['revision'], 'synthetic')
                self.assertEqual(audit, {
                    'version': 'government-input-scope-v1', 'scope': 'government-only',
                    'source_use': 'for-profit',
                    'catalog_sha256': hashlib.sha256((root / 'catalog/surveys.json').read_bytes()).hexdigest(),
                    'admitted_source_ids': ['leaf', 'middle', 'original'],
                    'excluded_source_ids': ['cycle', 'laundered', 'private', 'unknown-parent']})
                self.assertEqual(len(audit['catalog_sha256']), 64)
                for original, retained in zip([manifest['surveys'][i] for i in (0, 2, 3)], selected['surveys']):
                    self.assertIs(original, retained)
            with self.case('empty-inventory'):
                empty = {'surveys': []}; empty_root = self.root / 'empty'
                fixture.configure(empty_root, empty)
                selected, audit = scope.scoped_manifest(empty_root, empty)
                self.assertEqual(selected, empty)
                self.assertEqual(audit['admitted_source_ids'], [])
                self.assertEqual(audit['excluded_source_ids'], [])
            with self.case('literal-identities'):
                # Nonempty strings only: do not add a grammar or strip/casefold.
                literals = {'surveys': [fixture.row(' x '), fixture.row('x'),
                                        fixture.row('X'), fixture.row(' ')]}
                literal_root = self.root / 'literal'
                fixture.configure(literal_root, literals)
                selected, audit = scope.scoped_manifest(literal_root, literals)
                self.assertEqual(selected['surveys'], literals['surveys'])
                self.assertEqual(audit['admitted_source_ids'], [' ', ' x ', 'X', 'x'])
            for label, value in [('all-valid-identity', manifest),
                                 ('all-malformed-identity', {'surveys': [None, {}, {'id': ''}]})]:
                with self.case(label), patch.dict(os.environ, {'SKIPPERCAST_SOURCE_SCOPE': 'all'}):
                    all_root = self.root / label
                    fixture.write_json(all_root / 'deployments/production.json', {
                        'source_scope': 'all', 'source_use': 'for-profit', 'monetization': 'paid'})
                    with patch.object(scope, 'government_row') as filtering, patch.object(scope, 'sha256') as hashing:
                        selected, audit = scope.scoped_manifest(all_root, value)
                    self.assertIs(selected, value); self.assertIsNone(audit)
                    filtering.assert_not_called(); hashing.assert_not_called()
            with self.case('configured-scope'), patch.dict(os.environ):
                os.environ.pop('SKIPPERCAST_SOURCE_SCOPE', None)
                os.environ.pop('SKIPPERCAST_SOURCE_USE', None)
                self.assertEqual(scope.processing_scope(root), 'government-only')
            failures = {
                'configured-weakening': ('Environment cannot weaken', {'SKIPPERCAST_SOURCE_SCOPE': 'all'}),
                'missing-marker': ('matching isolated-root marker', {}),
                'wrong-root-marker': ('matching isolated-root marker', {}),
                'noncommercial': ('explicit for-profit', {}),
                'unknown-scope': ('Unknown seafloor input source scope', {'SKIPPERCAST_SOURCE_SCOPE': 'unknown'}),
                'default-marked-root': ('Default processing cannot use', {'SKIPPERCAST_SOURCE_SCOPE': 'all'}),
            }
            for label, (message, env) in failures.items():
                with self.case(label):
                    bad_root = self.root / label
                    fixture.configure(bad_root, manifest)
                    if label == 'missing-marker':
                        # No deletion: a fresh configuration with no marker.
                        bad_root = self.root / 'never-marked'
                        fixture.write_json(bad_root / 'deployments/production.json', {
                            'source_scope': 'government-only', 'source_use': 'for-profit', 'monetization': 'paid'})
                    if label == 'wrong-root-marker':
                        fixture.write_json(bad_root / 'var/seafloor/input-scope.json', {
                            'version': 1, 'scope': 'government-only', 'isolated_root': str(self.root / 'different')})
                    if label == 'noncommercial':
                        fixture.write_json(bad_root / 'deployments/production.json', {
                            'source_scope': 'government-only', 'source_use': 'noncommercial', 'monetization': 'none'})
                        env = {'SKIPPERCAST_SOURCE_USE': 'noncommercial'}
                    if label == 'default-marked-root':
                        fixture.write_json(bad_root / 'deployments/production.json', {
                            'source_scope': 'all', 'source_use': 'for-profit', 'monetization': 'paid'})
                    with patch.dict(os.environ, env), patch.object(scope, 'sha256') as hashing, \
                            patch.object(scope, 'government_row') as filtering:
                        with self.assertRaisesRegex(ValueError, message):
                            scope.scoped_manifest(bad_root, fixture.invalid_cases()['identical'])
                        hashing.assert_not_called(); filtering.assert_not_called()
            with self.case('rights-unchanged'):
                public = fixture.row('original')
                self.assertEqual(rights.source_rights(public, use='for-profit')['license'], 'public-domain-us-gov')
                with self.assertRaisesRegex(ValueError, 'express producer permission'):
                    rights.source_rights(fixture.row('private', 'csumb-public-use-noncommercial'), use='for-profit')

    def test_negative_control(self):
        manifest = fixture.invalid_cases()['private-public']
        fixture.configure(self.root, manifest)
        with self.product() as (scope, rights):
            self.assertEqual(scope.processing_scope(self.root), 'government-only')
            self.assertEqual(rights.deployment_use(self.root), 'for-profit')
            observed = {}
            with self.case('last-row-wins-detected'):
                # On the unchanged baseline this attribute is absent. create=True
                # leaves baseline product bytes untouched and still demonstrates
                # the exact last-row-wins failure; restored-positive then stays red.
                with patch.object(scope, '_validate_catalog_ids', return_value=None, create=True):
                    with self.assertRaisesRegex(AssertionError, '^ValueError not raised$') as caught:
                        self.refusal(scope, self.root, manifest, observed)
                selected, audit = observed['result']
                self.assertEqual([r['id'] for r in selected['surveys']], ['parent', 'child'])
                self.assertEqual(audit['admitted_source_ids'], ['child', 'parent'])
                self.assertGreater(observed['hash_calls'], 0)
                self.assertGreater(observed['lineage_calls'], 0)
                type(self).negative_outcomes.append({
                    'inner_failure': str(caught.exception),
                    'accepted_ids': [r['id'] for r in selected['surveys']],
                    'hash_calls': observed['hash_calls'], 'lineage_calls': observed['lineage_calls']})
            with self.case('restored-duplicate-refusal'):
                self.refusal(scope, self.root, manifest)
            with self.case('restored-unique-positive'):
                valid_root = self.root / 'restored-valid'; valid = fixture.unique_catalog()
                fixture.configure(valid_root, valid)
                selected, _ = scope.scoped_manifest(valid_root, valid)
                self.assertEqual([r['id'] for r in selected['surveys']], ['leaf', 'middle', 'original'])

    def test_preservation(self):
        with self.product() as (scope, _):
            with self.case('invalid-inputs-unchanged'):
                for name, manifest in fixture.invalid_cases().items():
                    root = self.root / name; fixture.configure(root, manifest)
                    before_files = fixture.snapshot(root); before_input = deepcopy(manifest)
                    originals = list(manifest['surveys']) if isinstance(manifest.get('surveys'), list) else []
                    self.refusal(scope, root, manifest)
                    self.assertEqual(manifest, before_input)
                    self.assertEqual(fixture.snapshot(root), before_files)
                    if originals:
                        for original, retained in zip(originals, manifest['surveys']):
                            self.assertIs(original, retained)
            with self.case('valid-inputs-unchanged'):
                root = self.root / 'valid'; manifest = fixture.unique_catalog()
                fixture.configure(root, manifest)
                before_files = fixture.snapshot(root); before_input = deepcopy(manifest)
                scope.scoped_manifest(root, manifest)
                self.assertEqual(manifest, before_input)
                self.assertEqual(fixture.snapshot(root), before_files)
        with self.case('peer-state-restored'):
            def peer_state():
                product = {k: (id(v), dict(vars(v))) for k, v in sys.modules.items()
                           if k == 'skippercast' or k.startswith('skippercast.')}
                return (dict(os.environ), list(sys.path), list(sys.meta_path),
                        sys.dont_write_bytecode, socket.socket, socket.getaddrinfo,
                        subprocess.Popen, os.system, product)
            before = peer_state()
            harmless = unittest.FunctionTestCase(lambda: self.assertEqual(peer_state(), before))
            result = unittest.TestResult(); harmless.run(result)
            self.assertTrue(result.wasSuccessful())
            with fixture.offline_product(self.root / 'peer') as (scope, _, _, violations):
                fixture.configure(self.root / 'peer', fixture.unique_catalog())
                scope.scoped_manifest(self.root / 'peer', fixture.unique_catalog())
                self.assertEqual(violations, [])
            harmless = unittest.FunctionTestCase(lambda: self.assertEqual(peer_state(), before))
            result = unittest.TestResult(); harmless.run(result)
            self.assertTrue(result.wasSuccessful())
            self.assertEqual(result.testsRun, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""SC15A: pure held-packet ownership, real authority predicates, no source I/O."""
from contextlib import contextmanager
import copy
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

from tests._support import ROOT, FIXTURES

_spec = importlib.util.spec_from_file_location('sc15a_fixture_support', FIXTURES / 'sc15a-packet-copy' / 'support.py')
if _spec is None or _spec.loader is None:
    raise RuntimeError('SC15A fixture loader unavailable')
S = importlib.util.module_from_spec(_spec)
with patch.object(sys, 'dont_write_bytecode', True):
    _spec.loader.exec_module(S)
CASES = []
METHODS = []

class PacketCopyTest(unittest.TestCase):
    def run(self, result=None):
        METHODS.append(self.id())
        print('METHOD ' + self.id())
        first = len(S.OBSERVATIONS)
        outcome = super().run(result)
        print('IMPORT_TRACE ' + json.dumps(S.OBSERVATIONS[first:], sort_keys=True))
        return outcome

    def setUp(self):
        base = Path(S.OUTPUT_BASE or os.environ.get('SC15A_OUTPUT_ROOT', ROOT.parent / 'out' / 'discovery'))
        base.mkdir(parents=True, exist_ok=True)
        # Only this fixture-owned directory is removed by TemporaryDirectory.
        self.temp = tempfile.TemporaryDirectory(prefix='sc15a-state-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @contextmanager
    def case(self, name):
        CASES.append(self._testMethodName + ':' + name)
        print('CASE ' + self._testMethodName + ':' + name)
        with self.subTest(case=name):
            yield

    def _assert_initial(self, api, profiles, saved, policy, f):
        grant = f['grant']
        self.assertIs(saved.continuation_grant(grant), grant)
        domain = profiles.grant_identity(grant)
        for key in S.KEYS:
            self.assertEqual(domain[key], grant[key])
        before = S.encoded(f)
        result = S.packet(api, f)
        self.assertEqual(S.encoded(f), before, 'construction mutated input')
        expected = S.expected_packet(self.root)
        self.assertEqual(S.encoded(result), S.encoded(expected), 'baseline canonical bytes differ')
        self.assertEqual(api.digest(result), S.sha_bytes(S.encoded(expected)))
        self.assertEqual(result['scientific_policy'], policy.policy_for_profile(grant['execution_profile'], result))
        self.assertFalse(result['execution_authorized'])
        return result

    def _assert_isolation(self, api, profiles, saved, policy, direction, field):
        f = S.load_input(self.root)
        result = self._assert_initial(api, profiles, saved, policy, f)
        grant = f['grant']
        grant_before, packet_before = S.encoded(grant), S.encoded(result)
        descriptor_keys = set(grant['saved_area_adoption'])
        new = 'metadata/adoption-altered.json' if field == 'path' else '9' * 64
        if direction == 'packet-to-grant':
            result['saved_area_adoption'][field] = new
            self.assertEqual(S.encoded(grant), grant_before, 'input grant changed through packet alias')
            self.assertNotEqual(S.encoded(result), packet_before)
        else:
            grant['saved_area_adoption'][field] = new
            self.assertEqual(S.encoded(result), packet_before, 'packet changed through input grant alias')
            self.assertNotEqual(S.encoded(grant), grant_before)
        self.assertEqual(set(grant['saved_area_adoption']), descriptor_keys)
        self.assertEqual(set(result['saved_area_adoption']), descriptor_keys)

    def test_positive_contract(self):
        with S.product_context(self.root) as modules:
            for direction in ('packet-to-grant', 'grant-to-packet'):
                for field in ('path', 'sha256'):
                    with self.case(direction + '-' + field):
                        self._assert_isolation(*modules, direction, field)

    def test_rejects_malformed(self):
        with S.product_context(self.root) as (api, profiles, saved, policy):
            for key in S.KEYS[1:]:
                with self.case('missing-' + key):
                    f = S.load_input(self.root)
                    del f['grant'][key]
                    before = S.encoded(f)
                    if key == 'saved_area_adoption':
                        with self.assertRaisesRegex(KeyError, 'saved_area_adoption'):
                            S.packet(api, f)
                    else:
                        with self.assertRaisesRegex(ValueError, 'exact adopted-A six-admission nonrefundable authority required'):
                            S.packet(api, f)
                    self.assertEqual(S.encoded(f), before)
            for value in (True, None, 'absent'):
                with self.case('execution-' + str(value)):
                    f = S.load_input(self.root)
                    if value == 'absent':
                        del f['grant']['execution_authorized']
                    else:
                        f['grant']['execution_authorized'] = value
                    with self.assertRaisesRegex(ValueError, 'packet preparation requires explicitly held grant'):
                        S.packet(api, f)
            for value in ('wrong-contract', ''):
                with self.case('continuation-' + repr(value)):
                    f = S.load_input(self.root)
                    f['grant']['saved_area_continuation_contract'] = value
                    with self.assertRaisesRegex(ValueError, 'explicit saved-area continuation contract required'):
                        S.packet(api, f)
            for field, value in (('schema', 'wrong'), ('stage', 'qualify')):
                with self.case('template-' + field):
                    f = S.load_input(self.root)
                    f['template'][field] = value
                    with self.assertRaisesRegex(ValueError, 'acquisition template required'):
                        S.packet(api, f)

    def test_baseline_compatibility(self):
        with S.product_context(self.root) as (api, profiles, saved, policy):
            with self.case('complete-held-baseline-bytes-and-digest'):
                f = S.load_input(self.root)
                result = self._assert_initial(api, profiles, saved, policy, f)
                profiles.validate_grant_packet(f['grant'], result)
                self.assertFalse(Path(f['grant']['source_root']).exists())
                self.assertFalse(Path(f['grant']['output_root']).exists())
            for presence in ('absent', 'null'):
                with self.case('no-continuation-removes-inherited-' + presence):
                    f = S.load_input(self.root)
                    for key in S.KEYS:
                        f['template'][key] = copy.deepcopy(f['grant'][key])
                        del f['grant'][key]
                    if presence == 'null':
                        f['grant']['saved_area_continuation_contract'] = None
                    expected = S.expected_packet(self.root)
                    for key in S.KEYS:
                        del expected[key]
                    result = S.packet(api, f)
                    self.assertEqual(S.encoded(result), S.encoded(expected))
                    self.assertEqual(api.digest(result), S.sha_bytes(S.encoded(expected)))
                    self.assertTrue(set(S.KEYS).isdisjoint(result))
                    profiles.validate_grant_packet(f['grant'], result)
            for side in (32, 64):
                with self.case('inherited-larger-authority-retains-refusal-' + str(side)):
                    f = S.load_input(self.root)
                    for key in (*S.KEYS, 'ordered_scope_contract', 'geographic_review', 'output_retention', 'output_root', 'larger_runtime_contract'):
                        f['grant'].pop(key, None)
                    f['grant'].update(window_side=side, window_set=[[0,side,side,side],[side,side,side,side],[0,0,side,side],[side,0,side,side]])
                    f['template']['larger_runtime_contract'] = 'inherited-unsupported-authority'
                    result = S.packet(api, f)
                    self.assertEqual(result['larger_runtime_contract'], 'inherited-unsupported-authority')
                    self.assertFalse(result['execution_authorized'])
                    with self.assertRaisesRegex(ValueError, 'packet managed runtime contract differs from immutable grant'):
                        profiles.validate_grant_packet(f['grant'], result)

    def test_deciding_negative_control(self):
        with S.product_context(self.root) as modules:
            api, profiles, saved, policy = modules
            real = api.canonical_packet
            for direction in ('packet-to-grant', 'grant-to-packet'):
                for field in ('path', 'sha256'):
                    with self.case('mutant-' + direction + '-' + field):
                        with patch.object(api, 'canonical_packet', S.legacy_constructor(real)):
                            reason = 'input grant changed through packet alias' if direction == 'packet-to-grant' else 'packet changed through input grant alias'
                            with self.assertRaisesRegex(AssertionError, reason):
                                self._assert_isolation(*modules, direction, field)
                        self.assertIs(api.canonical_packet, real)
                        print('MUTANT_DETECTED ' + direction + '-' + field + ' baseline-bytes-pass')
                    with self.case('restored-' + direction + '-' + field):
                        self._assert_isolation(*modules, direction, field)

    def test_isolation_and_discovery(self):
        # An unchanged stdlib-only peer runs before and after fixture import/teardown.
        from tests.contract.test_test_layout import LayoutTest
        def peer():
            result = unittest.TestResult()
            LayoutTest('test_every_layer_is_a_package').run(result)
            self.assertEqual(result.testsRun, 1)
            self.assertTrue(result.wasSuccessful(), str(result.errors + result.failures))
            return result.testsRun
        before_modules = {n: m for n,m in sys.modules.items() if n == 'skippercast' or n.startswith('skippercast.')}
        before = (list(sys.path), dict(os.environ), sys.dont_write_bytecode, socket.socket.connect, subprocess.Popen)
        with self.case('peer-before'):
            self.assertEqual(peer(), 1)
        with self.case('synthetic-import-and-real-predicates'):
            with S.product_context(self.root) as modules:
                self._assert_initial(*modules, S.load_input(self.root))
                # Verify guard identities without attempting any forbidden action.
                self.assertIs(subprocess.Popen, S.denied)
                self.assertIs(socket.socket.connect, S.denied)
        with self.case('teardown-restored-modules-paths-environment-guards'):
            after_modules = {n: m for n,m in sys.modules.items() if n == 'skippercast' or n.startswith('skippercast.')}
            self.assertEqual(after_modules, before_modules)
            self.assertEqual((list(sys.path), dict(os.environ), sys.dont_write_bytecode, socket.socket.connect, subprocess.Popen), before)
        with self.case('peer-after'):
            self.assertEqual(peer(), 1)
        with self.case('five-required-methods-registered'):
            self.assertEqual(unittest.defaultTestLoader.getTestCaseNames(type(self)), [
                'test_baseline_compatibility', 'test_deciding_negative_control', 'test_isolation_and_discovery',
                'test_positive_contract', 'test_rejects_malformed'])

if __name__ == '__main__':
    unittest.main()

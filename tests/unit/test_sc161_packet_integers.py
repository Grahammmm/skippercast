"""SC161: contained/finite packet shape bindings refuse numeric lookalikes.

validate_grant_packet must require strict ints (type(value) is int) for a
contained packet's window_side/window_count, and a four-element list of strict
ints for every named finite profile's native_window, before the existing
equality/membership checks. The unnamed legacy branch is unchanged.

Ordinary unittest discovery is safe: no product import, write, audit hook or
environment change happens at module import time. Product imports occur inside
the reversible offline guard from tools/run_sc161_packet_integers.py.
"""
from copy import deepcopy
import builtins
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

from tests._support import FIXTURES, ROOT as REPO

FIXTURE = FIXTURES / 'sc161-packet-integers'
RUNNER = REPO / 'tools/run_sc161_packet_integers.py'
CODE = 'packet_integer_binding_invalid'
OUTSIDE = 'window outside immutable finite grant'
SHAPE = 'contained input shape/count differs from immutable grant'
MISSING = object()
PACKET_KEYS = ('execution_profile', 'window_side', 'window_count', 'source', 'source_root',
               'source_relative_path', 'ordered_scope_contract', 'geographic_review',
               'output_retention', 'output_root', 'larger_runtime_contract', 'support_policy')


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError('missing test support')
    module = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


def equality_only(p):
    """Test-local callable retaining the pinned base's equality-only shape predicate.

    Verbatim logic of validate_grant_packet at base 8a805820 (profiles.py lines
    106-127), bound to the genuine grant_identity/profile of the candidate. Used
    only as the deciding negative control and as the baseline-domain oracle.
    """
    def validate(grant, packet):
        domain = p.grant_identity(grant); selected = p.profile(domain.get('execution_profile'), domain)
        if packet.get('saved_area_continuation_contract') != grant.get('saved_area_continuation_contract'):
            raise ValueError('packet continuation domain differs')
        if grant.get('saved_area_continuation_contract') is not None and any(packet.get(k) != grant[k] for k in ('saved_area_adoption', 'source_volume_cap_bytes', 'prior_effective_bytes', 'cumulative_limit_bytes')):
            raise ValueError('packet adoption/cumulative authority differs')
        if packet.get('larger_runtime_contract') != grant.get('larger_runtime_contract'):
            raise ValueError('packet managed runtime contract differs from immutable grant')
        if packet.get('source_reuse_contract') != grant.get('source_reuse_contract'):
            raise ValueError('packet source reuse contract differs from immutable grant')
        if grant.get('ordered_scope_contract') is not None:
            if any(packet.get(k) != grant[k] for k in ('ordered_scope_contract', 'geographic_review', 'output_retention', 'output_root')):
                raise ValueError('packet ordered geometry/output contract differs from immutable grant')
        if packet.get('execution_profile') != selected['name']: raise ValueError('input profile differs from immutable grant')
        if packet.get('support_policy') != domain.get('support_policy'): raise ValueError('packet support policy differs from immutable grant')
        if selected['name'] == p.CONTAINED and any(packet.get(k) != domain[k] for k in ('window_side', 'window_count')):
            raise ValueError('contained input shape/count differs from immutable grant')
        if any(packet.get(key) != domain[key] for key in ('source', 'source_root', 'source_relative_path')):
            raise ValueError('packet differs from exact source domain')
        if selected['name'] and packet.get('fixed_center_plan', {}).get('native_window') not in domain['window_set']:
            raise ValueError('window outside immutable finite grant')
        return domain
    return validate


def source():
    return {'path': 'synthetic.bag', 'sha256': 'a' * 64, 'bytes': 1}


def base_grant(**extra):
    grant = {'schema': 'coastal-authenticated-policy-v1', 'source': source(),
             'source_root': 'synthetic/source-root', 'source_relative_path': 'synthetic.bag'}
    grant.update(extra)
    return grant


def packet_for(grant, window):
    packet = {key: deepcopy(grant[key]) for key in PACKET_KEYS if key in grant}
    packet['fixed_center_plan'] = {'native_window': deepcopy(window)}
    return packet


def with_field(packet, key, value):
    packet = deepcopy(packet)
    if value is MISSING:
        packet.pop(key, None)
    else:
        packet[key] = value
    return packet


def with_window(packet, window):
    packet = deepcopy(packet)
    if window is MISSING:
        packet['fixed_center_plan'] = {}
    else:
        packet['fixed_center_plan'] = {'native_window': window}
    return packet


def typed(value):
    """Type-exact representation: True, 1 and 1.0 are all distinct here."""
    return repr(value)


class PacketIntegerBindingTests(unittest.TestCase):
    OUTPUT_ROOT = None

    @classmethod
    def setUpClass(cls):
        cls.support = load_file('sc161_support', RUNNER)
        if cls.OUTPUT_ROOT is None:
            # CI may supply an inherited admitted output root. Never mutate env.
            inherited = os.environ.get('SKIPPERCAST_TEST_OUTPUT_ROOT')
            prefix = Path(inherited) if inherited else REPO.parent / 'out/discovery'
            cls.run_root = prefix / ('sc161-' + uuid.uuid4().hex)
            cls.run_root.mkdir(parents=True, exist_ok=False)
        else:
            cls.run_root = Path(cls.OUTPUT_ROOT)
        cls.cases = {}
        cls.control = {'expected': [], 'detected': [], 'inner_failures': {}, 'restored': False}
        cls.fixture = json.loads((FIXTURE / 'windows.json').read_text())
        cls.guard = cls.support.OfflineProduct(cls.run_root)
        cls.guard.__enter__()
        try:
            cls.p = importlib.import_module('skippercast.coastal.authenticated_v1.profiles')
            cls.policy = importlib.import_module('skippercast.coastal.authenticated_v1.policy')
            cls.common = importlib.import_module('skippercast.coastal.handoff.common')
            cls.origins = cls.guard.origins()
        except BaseException:
            cls.guard.__exit__(*sys.exc_info())
            raise
        cls.genuine = staticmethod(cls.p.validate_grant_packet)
        cls.constants = typed((cls.p.CONTAINED, cls.p.LARGER, cls.p.PARTIAL_SUPPORT,
                               cls.p.PARTIAL_WINDOWS, cls.p.ORDERED_SCOPE, cls.p.MANAGED_EIGHT_COPY))

    @classmethod
    def tearDownClass(cls):
        events = list(cls.guard.events)
        cls.guard.__exit__(None, None, None)
        cls.support.dump(cls.run_root / 'test-details.json', {
            'cases': cls.cases, 'module_origins': cls.origins, 'guard_events': events,
            'negative_control': cls.control, 'fixture_hashes': cls.support.fixture_hashes()})
        print('SC161_DETAILS=' + str(cls.run_root / 'test-details.json'))

    def setUp(self):
        self.validate = self.genuine

    # ------------------------------------------------------------ helpers

    def case(self, name):
        self.__class__.cases.setdefault(self._testMethodName, []).append(name)
        return self.subTest(case=name)

    def finish(self):
        recorded = self.__class__.cases.get(self._testMethodName, [])
        expected = self.support.EXPECTED_CASES[self._testMethodName]
        self.assertEqual((len(recorded), len(set(recorded))), (expected, expected),
                         'missing, extra or duplicate subcases')

    def old_validate(self, grant, packet):
        return equality_only(self.p)(grant, packet)

    def grants(self):
        f, p = self.fixture, self.p
        contained = lambda name, **extra: base_grant(
            execution_profile=p.CONTAINED, window_side=f[name]['side'], window_count=f[name]['count'],
            window_set=deepcopy(f[name]['windows']), **extra)
        ordered = dict(ordered_scope_contract=p.ORDERED_SCOPE, larger_runtime_contract=p.MANAGED_EIGHT_COPY,
                       geographic_review={'path': 'metadata/scope-review.json', 'sha256': 'e' * 64,
                                          'bytes': 1, 'contract': 'synthetic-scope-review'},
                       output_retention={'profile': 'coastal-managed-output-32-v2'},
                       output_root='synthetic/output')
        return {
            'unit': contained('unit'), 'premise': contained('premise'), 'pair': contained('pair'),
            'larger': base_grant(execution_profile=p.LARGER, window_set=deepcopy(f['larger']['windows'])),
            'partial': base_grant(execution_profile=p.CONTAINED, window_side=128, window_count=4,
                                  window_set=deepcopy(p.PARTIAL_WINDOWS), support_policy=p.PARTIAL_SUPPORT,
                                  **deepcopy(ordered)),
            'partial-strict': base_grant(execution_profile=p.CONTAINED, window_side=128, window_count=4,
                                         window_set=deepcopy(p.PARTIAL_WINDOWS), **deepcopy(ordered)),
            'legacy': base_grant(),
        }

    def assert_integer_refusal(self, grant, packet):
        """THE regression assertion: a malformed shape is refused under the new code."""
        with self.assertRaises(ValueError) as caught:
            self.validate(grant, packet)
        self.assertIn(CODE, str(caught.exception))

    def assert_accepts_baseline(self, grant, packet):
        result = self.validate(grant, packet)
        self.assertEqual(result, self.p.grant_identity(grant))
        self.assertEqual(typed(result), typed(self.old_validate(grant, packet)))
        return result

    def message(self, call, *args):
        try:
            call(*args)
        except ValueError as exc:
            return str(exc)
        return None

    def decisive_cases(self):
        """Otherwise-equal bool/float lookalikes: only the new type check decides."""
        g = self.grants()
        unit = packet_for(g['unit'], g['unit']['window_set'][0])
        premise = packet_for(g['premise'], g['premise']['window_set'][0])
        larger = packet_for(g['larger'], g['larger']['window_set'][0])
        partial = packet_for(g['partial'], g['partial']['window_set'][-1])
        return [
            ('unit-side-true', g['unit'], with_field(unit, 'window_side', True)),
            ('unit-count-true', g['unit'], with_field(unit, 'window_count', True)),
            ('unit-side-float', g['unit'], with_field(unit, 'window_side', 1.0)),
            ('premise-side-float-count-true', g['premise'],
             with_field(with_field(premise, 'window_side', 2.0), 'window_count', True)),
            ('unit-window-pos0-true', g['unit'], with_window(unit, [True, 0, 1, 1])),
            ('unit-window-pos1-false', g['unit'], with_window(unit, [1, False, 1, 1])),
            ('unit-window-pos2-float', g['unit'], with_window(unit, [1, 0, 1.0, 1])),
            ('larger-window-pos0-false', g['larger'], with_window(larger, [False, 128, 128, 128])),
            ('partial-window-pos3-float', g['partial'],
             with_window(partial, g['partial']['window_set'][-1][:3] + [128.0])),
        ]

    # ------------------------------------------------------------ A1 regression

    def test_regression(self):
        g = self.grants()
        bases = {name: packet_for(g[name], g[name]['window_set'][0])
                 for name in ('unit', 'premise', 'pair', 'larger')}
        bases['partial'] = dict(packet_for(g['partial'], g['partial']['window_set'][0]))
        # side/count: true, false, float, string, null, missing — each independently.
        variants = {'true': True, 'false': False, 'float': 1.0, 'string': '1', 'null': None, 'missing': MISSING}
        for field in ('window_side', 'window_count'):
            for label, value in variants.items():
                with self.case('unit-%s-%s' % (field, label)):
                    if label in ('true', 'float'):
                        self.assertTrue(value == g['unit'][field])  # otherwise-equal: decided by type alone
                    self.assert_integer_refusal(g['unit'], with_field(bases['unit'], field, value))
        # The measured premise: side=2.0 and count=True against side=2/count=1.
        for label, changes in (('side-float', {'window_side': 2.0}), ('count-true', {'window_count': True}),
                               ('both', {'window_side': 2.0, 'window_count': True})):
            with self.case('premise-' + label):
                packet = deepcopy(bases['premise'])
                packet.update(changes)
                self.assertEqual(packet['window_side'], 2)
                self.assertEqual(packet['window_count'], 1)
                self.assert_integer_refusal(g['premise'], packet)
        for name, side, count in (('pair', 32, 2), ('partial', 128, 4)):
            for field, value in (('window_side', float(side)), ('window_count', float(count))):
                with self.case('%s-%s-float' % (name, field)):
                    self.assertTrue(value == g[name][field])
                    self.assert_integer_refusal(g[name], with_field(bases[name], field, value))
        # native_window: every position with bool/float/string/null.
        window = g['unit']['window_set'][0]
        for pos in range(4):
            for label, convert in (('bool', bool), ('float', float), ('string', str), ('null', lambda v: None)):
                with self.case('unit-window-pos%d-%s' % (pos, label)):
                    bad = list(window)
                    bad[pos] = convert(window[pos])
                    if label in ('bool', 'float'):
                        self.assertTrue(bad == window)  # otherwise-equal under Python equality
                    self.assert_integer_refusal(g['unit'], with_window(bases['unit'], bad))
        larger_window = g['larger']['window_set'][0]
        for pos in range(4):
            with self.case('larger-window-pos%d-float' % pos):
                bad = list(larger_window)
                bad[pos] = float(bad[pos])
                self.assertTrue(bad == larger_window)
                self.assert_integer_refusal(g['larger'], with_window(bases['larger'], bad))
        with self.case('larger-window-pos0-bool'):
            bad = [False] + larger_window[1:]
            self.assertTrue(bad == larger_window)
            self.assert_integer_refusal(g['larger'], with_window(bases['larger'], bad))
        partial_last = g['partial']['window_set'][-1]
        partial_packet = packet_for(g['partial'], partial_last)
        for pos in range(4):
            with self.case('partial-window-pos%d-float' % pos):
                bad = list(partial_last)
                bad[pos] = float(bad[pos])
                self.assertTrue(bad == partial_last)
                self.assert_integer_refusal(g['partial'], with_window(partial_packet, bad))
        # native_window container shapes.
        containers = {
            'native-missing': MISSING, 'null': None, 'object': {'0': 1, '1': 0, '2': 1, '3': 1},
            'tuple': (1, 0, 1, 1), 'string': '1,0,1,1', 'len0': [], 'len3': [1, 0, 1],
            'len5': [1, 0, 1, 1, 1], 'nested': [[1, 0, 1, 1]],
        }
        for label, value in containers.items():
            with self.case('unit-container-' + label):
                self.assert_integer_refusal(g['unit'], with_window(bases['unit'], value))
        for label, value in (('plan-missing', MISSING), ('plan-null', None), ('plan-list', [[1, 0, 1, 1]])):
            with self.case('unit-container-' + label):
                self.assert_integer_refusal(g['unit'], with_field(bases['unit'], 'fixed_center_plan', value))
        for label, value in (('tuple', tuple(larger_window)), ('len3', larger_window[:3])):
            with self.case('larger-container-' + label):
                self.assert_integer_refusal(g['larger'], with_window(bases['larger'], value))
        # Valid integer windows at the first and last admitted positions: exact baseline domain.
        for name in ('unit', 'pair', 'larger', 'partial'):
            positions = (('first', 0),) if name == 'unit' else (('first', 0), ('last', -1))
            for label, index in positions:
                with self.case('%s-positive-%s' % (name, label)):
                    self.assert_accepts_baseline(g[name], packet_for(g[name], g[name]['window_set'][index]))
        # Out-of-grant integer windows keep the existing error.
        for name, window in self.fixture['out_of_grant'].items():
            with self.case('%s-out-of-grant' % name):
                with self.assertRaises(ValueError) as caught:
                    self.validate(g[name], packet_for(g[name], window))
                self.assertIn(OUTSIDE, str(caught.exception))
                self.assertNotIn(CODE, str(caught.exception))
        self.finish()

    # ------------------------------------------------------------ compatibility

    def test_compatibility(self):
        g = self.grants()
        # Legacy unnamed profile: no new shape check, identical to the pinned base.
        legacy = packet_for(g['legacy'], None)
        for label, packet in (('legacy-lookalike-window', with_window(legacy, [True, 0.0, 'x', None])),
                              ('legacy-no-plan', with_field(legacy, 'fixed_center_plan', MISSING)),
                              ('legacy-lookalike-shape', dict(legacy, window_side=True, window_count=1.0)),
                              ('legacy-tuple-window', with_window(legacy, (1, 0, 1, 1)))):
            with self.case(label):
                self.assert_accepts_baseline(g['legacy'], packet)
        # Strict and partial grant identities/digests are unchanged versus the base predicate.
        for name in ('pair', 'partial'):
            with self.case('%s-domain-digest-unchanged' % name):
                packet = packet_for(g[name], g[name]['window_set'][0])
                self.assertEqual(self.common.digest(self.validate(g[name], packet)),
                                 self.common.digest(self.old_validate(g[name], packet)))
        with self.case('strict-and-partial-policy-digests-distinct'):
            strict = {'window_side': 128, 'window_count': 4}
            partial = dict(strict, support_policy=self.p.PARTIAL_SUPPORT)
            self.assertNotEqual(self.policy.policy_sha(self.p.CONTAINED, strict),
                                self.policy.policy_sha(self.p.CONTAINED, partial))
            self.assertNotIn('support_policy', self.policy.policy_for_profile(self.p.CONTAINED, strict))
            self.assertNotEqual(self.common.digest(self.p.grant_identity(g['partial'])),
                                self.common.digest(self.p.grant_identity(g['partial-strict'])))
        # Partial-support bindings and every existing error stay identical to the base.
        partial_packet = packet_for(g['partial'], g['partial']['window_set'][0])
        unit_packet = packet_for(g['unit'], g['unit']['window_set'][0])
        existing = [
            ('partial-missing-support-policy', g['partial'], with_field(partial_packet, 'support_policy', MISSING),
             'support policy'),
            ('strict-grant-partial-packet', g['partial-strict'], partial_packet, 'support policy'),
            ('source-differs', g['unit'], dict(unit_packet, source_relative_path='other.bag'), 'exact source domain'),
            ('profile-differs', g['unit'], dict(unit_packet, execution_profile=self.p.LARGER), 'input profile differs'),
            ('integer-side-differs', g['unit'], dict(unit_packet, window_side=2), SHAPE),
            ('integer-count-differs', g['unit'], dict(unit_packet, window_count=2), SHAPE),
            ('ordered-output-differs', g['partial'], dict(partial_packet, output_root='synthetic/elsewhere'),
             'ordered geometry/output'),
            ('runtime-contract-differs', g['partial'], with_field(partial_packet, 'larger_runtime_contract', MISSING),
             'managed runtime contract'),
        ]
        for label, grant, packet, reason in existing:
            with self.case(label):
                new = self.message(self.validate, grant, packet)
                self.assertIsNotNone(new)
                self.assertIn(reason, new)
                self.assertEqual(new, self.message(self.old_validate, grant, packet))
        self.finish()

    # ------------------------------------------------------------ deciding negative control

    def test_negative_control(self):
        cases = self.decisive_cases()
        g = self.grants()
        positive = packet_for(g['unit'], g['unit']['window_set'][0])
        control = self.__class__.control
        control['expected'] = [label for label, _, _ in cases]
        detected = []
        with patch.object(self, 'validate', self.old_validate):
            for label, grant, packet in cases:
                with self.case('control-detects-' + label):
                    try:
                        self.assert_integer_refusal(grant, packet)  # SAME regression assertion
                    except self.failureException as inner:
                        detected.append(label)
                        control['inner_failures'][label] = str(inner).splitlines()[0]
                    else:
                        self.fail('equality-only control was not detected: ' + label)
            with self.case('control-integer-positive'):
                self.assert_accepts_baseline(g['unit'], positive)
        control['detected'] = detected
        with self.case('control-restored'):
            self.assertEqual(self.validate, self.genuine)
            self.assertIs(self.p.validate_grant_packet, self.genuine)
        for label, grant, packet in cases:
            with self.case('restored-' + label):
                self.assert_integer_refusal(grant, packet)
        with self.case('restored-integer-positive'):
            self.assert_accepts_baseline(g['unit'], positive)
        control['restored'] = self.validate == self.genuine
        self.finish()

    # ------------------------------------------------------------ preservation

    def test_preservation(self):
        g = self.grants()
        unit = packet_for(g['unit'], g['unit']['window_set'][0])
        inputs = [
            ('unit-side-true', g['unit'], with_field(unit, 'window_side', True)),
            ('unit-count-float', g['unit'], with_field(unit, 'window_count', 1.0)),
            ('unit-window-float', g['unit'], with_window(unit, [1.0, 0, 1, 1])),
            ('unit-window-tuple', g['unit'], with_window(unit, (1, 0, 1, 1))),
            ('unit-plan-null', g['unit'], with_field(unit, 'fixed_center_plan', None)),
            ('partial-positive', g['partial'], packet_for(g['partial'], g['partial']['window_set'][-1])),
            ('larger-positive', g['larger'], packet_for(g['larger'], g['larger']['window_set'][-1])),
        ]
        for label, grant, packet in inputs:
            with self.case('inputs-unchanged-' + label):
                before = (typed(grant), typed(packet))
                try:
                    self.validate(grant, packet)
                except ValueError:
                    pass
                self.assertEqual((typed(grant), typed(packet)), before)
        with self.case('result-is-independent-copy'):
            grant = g['pair']
            packet = packet_for(grant, grant['window_set'][0])
            first = self.validate(grant, packet)
            first['window_set'][0][0] = 999
            self.assertEqual(typed(self.validate(grant, packet)), typed(self.p.grant_identity(grant)))
            self.assertEqual(grant['window_set'][0][0], 0)
        originals = {'open': builtins.open, 'io.open': io.open, 'popen': subprocess.Popen,
                     'connect': socket.socket.connect, 'system': os.system}
        with self.case('no-side-effects-on-refusal'):
            events = []
            def record(*args, **kwargs):
                events.append(args[:1])
                raise RuntimeError('side effect during pure predicate')
            with patch.object(builtins, 'open', record), patch.object(io, 'open', record), \
                    patch.object(subprocess, 'Popen', record), patch.object(socket.socket, 'connect', record), \
                    patch.object(os, 'system', record):
                for _, grant, packet in self.decisive_cases() + inputs[:5]:
                    with self.assertRaises(ValueError):
                        self.validate(grant, packet)
            self.assertEqual(events, [])
        with self.case('patches-restored'):
            self.assertIs(builtins.open, originals['open'])
            self.assertIs(io.open, originals['io.open'])
            self.assertIs(subprocess.Popen, originals['popen'])
            self.assertIs(socket.socket.connect, originals['connect'])
            self.assertIs(os.system, originals['system'])
        with self.case('module-constants-unchanged'):
            self.assertEqual(typed((self.p.CONTAINED, self.p.LARGER, self.p.PARTIAL_SUPPORT, self.p.PARTIAL_WINDOWS,
                                    self.p.ORDERED_SCOPE, self.p.MANAGED_EIGHT_COPY)), self.constants)
        with self.case('product-origin-is-candidate'):
            self.assertTrue(Path(self.p.__file__).resolve().is_relative_to(REPO / 'src'))
            self.assertEqual(self.origins['skippercast.coastal.authenticated_v1.profiles'],
                             str((REPO / 'src/skippercast/coastal/authenticated_v1/profiles.py').resolve()))
        self.finish()


if __name__ == '__main__':
    unittest.main()

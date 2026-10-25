"""SC172: byte-bound multibeam preparation receipts decode as strict JSON.

After the existing byte-bound and SHA256 checks, reviewed_receipt must decode
the exact receipt bytes with a local strict decoder: repeated decoded object
keys at any depth, NaN/Infinity tokens, overflowing numbers and a non-object
top level are refused with ValueError. Byte bounds, hash checks, receipt
semantics, count checks and the existing source/public-claim refusals are
unchanged, and refusal never publishes a paired cache or qualifies a source.

Ordinary unittest discovery is safe: no product import, write, audit hook or
environment change happens at module import time. Product imports occur inside
the reversible offline guard from tools/run_sc172_preparation_json.py.
"""
from copy import deepcopy
import builtins
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / 'tests/fixtures/sc172-preparation-json'
RUNNER = REPO / 'tools/run_sc172_preparation_json.py'
MODULE = 'skippercast.seafloor.adapters.multibeam_grid'
STRICT = 'not strict JSON'
SOURCE_BYTES = b'SC172 synthetic derived multibeam grid bytes; not a raster.\n'
SEMANTICS = 'Unreviewed preparation semantics or public/source claims'
PROVENANCE = 'Incomplete original/table/grid provenance'
PEER = {}
_SUPPORT = {}


def load_support():
    """The shared offline guard lives in the runner; loaded without bytecode."""
    if 'module' not in _SUPPORT:
        spec = importlib.util.spec_from_file_location('sc172_support', RUNNER)
        if spec is None or spec.loader is None:
            raise RuntimeError('missing test support')
        module = importlib.util.module_from_spec(spec)
        old = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = old
        _SUPPORT['module'] = module
    return _SUPPORT['module']


def ordinary_json_loads(data):
    """Named test-local callable: the pinned base's default json.loads decoding.

    Used only as the deciding negative control in place of the local strict
    decoder; it keeps default duplicate-key (last wins) and constant handling.
    """
    return json.loads(data)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def receipt_fields(output_sha256):
    """Producer-shaped receipt copied structurally from tests/gis/test_seafloor_multibeam_grid.py."""
    return {'scope': 'private-multibeam-grid-parity', 'output_sha256': output_sha256,
            'derived_bin_spacing_m': 5, 'vertical_datum': 'unknown', 'native_resolution': 'irregular soundings',
            'uncertainty': 'unknown', 'count_support_mismatches': 0, 'source_qualified': False,
            'fishing_target': False, 'exportable': False, 'new_measured_km2': 0,
            'new_physical_candidates': 0, 'new_public_locations': 0,
            'originals': {'original.mb57': 'a' * 64}, 'beam_table_sha256': ['b' * 64],
            'grid_sha256': ['c' * 64, 'd' * 64, 'e' * 64], 'grid_receipt_sha256': 'f' * 64,
            'horizontal_crs': 'EPSG:3310'}


def members(fields):
    """Raw (key-text, value-text) members of an object, for exact byte construction."""
    return [(json.dumps(k), json.dumps(v)) for k, v in fields.items()]


def render(raw_members):
    return ('{' + ', '.join(k + ': ' + v for k, v in raw_members) + '}').encode()


def replaced(raw_members, key, value_text):
    if json.dumps(key) not in [k for k, _ in raw_members]:
        raise AssertionError('constructor did not find ' + key)
    return [(k, value_text if k == json.dumps(key) else v) for k, v in raw_members]


def typed(value):
    """Type-exact representation: 0, 0.0, -0.0 and False are all distinct here."""
    return repr(value)


class JsonSpy:
    """Delegates to json but records every product-side loads call."""

    def __init__(self):
        self.calls = 0

    def loads(self, *args, **kwargs):
        self.calls += 1
        return json.loads(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(json, name)


def output_root():
    # CI may supply an inherited admitted output root. Never mutate env.
    inherited = os.environ.get('SKIPPERCAST_TEST_OUTPUT_ROOT')
    if inherited:
        prefix = Path(inherited)
    elif (REPO.parent / 'out').is_dir():
        prefix = REPO.parent / 'out/discovery'
    else:
        prefix = Path(tempfile.gettempdir())
    root = prefix / ('sc172-' + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    return root


class APeerBeforeTests(unittest.TestCase):
    """Harmless peer that runs before the SC172 class in ordinary discovery."""

    def test_peer(self):
        PEER['before'] = load_support().peer_state()
        self.assertNotIn(MODULE, sys.modules)


class PreparationReceiptJsonTests(unittest.TestCase):
    OUTPUT_ROOT = None

    @classmethod
    def setUpClass(cls):
        cls.support = load_support()
        cls.run_root = Path(cls.OUTPUT_ROOT) if cls.OUTPUT_ROOT is not None else output_root()
        cls.cases = {}
        cls.control = {'expected': [], 'detected': [], 'inner_failures': {}, 'restored': False}
        cls.fixture = json.loads((FIXTURE / 'cases.json').read_text())
        cls.counter = 0
        cls.guard = cls.support.OfflineProduct(cls.run_root)
        cls.guard.__enter__()
        try:
            cls.mg = importlib.import_module(MODULE)
            cls.origins = cls.guard.origins()
        except BaseException:
            cls.guard.__exit__(*sys.exc_info())
            raise
        cls.genuine = staticmethod(getattr(cls.mg, '_decode_receipt', None))
        cls.constants = typed((cls.mg.FORMAT, cls.mg.VERSION, cls.mg.DESCRIPTIONS))
        cls.patched = {'open': builtins.open, 'io.open': io.open, 'popen': subprocess.Popen,
                       'connect': socket.socket.connect, 'system': os.system}

    @classmethod
    def tearDownClass(cls):
        events = list(cls.guard.events)
        cls.guard.__exit__(None, None, None)
        cls.support.dump(cls.run_root / 'test-details.json', {
            'cases': cls.cases, 'module_origins': cls.origins, 'guard_events': events,
            'negative_control': cls.control, 'fixture_hashes': cls.support.fixture_hashes()})
        print('SC172_DETAILS=' + str(cls.run_root / 'test-details.json'))

    # ------------------------------------------------------------ helpers

    def case(self, name):
        self.__class__.cases.setdefault(self._testMethodName, []).append(name)
        return self.subTest(case=name)

    def finish(self):
        recorded = self.__class__.cases.get(self._testMethodName, [])
        expected = self.support.EXPECTED_CASES[self._testMethodName]
        self.assertEqual((len(recorded), len(set(recorded))), (expected, expected),
                         'missing, extra or duplicate subcases')

    def fresh(self):
        self.__class__.counter += 1
        folder = self.run_root / self._testMethodName / ('%04d' % self.counter)
        folder.mkdir(parents=True, exist_ok=False)
        return folder

    def row(self, receipt_sha256):
        """Otherwise-valid derived-grid row; the receipt hash is recomputed per case."""
        return {'id': 'sc172-fixture-grid', 'format': self.mg.FORMAT, 'kind': 'bathymetry',
                'status': 'candidate', 'license': 'unknown', 'resolution_m': 5, 'vertical_datum': 'unknown',
                'archive_member': 'unknown', 'sha256': sha(SOURCE_BYTES), 'bytes': len(SOURCE_BYTES),
                'grid_preparation': {'profile': self.mg.VERSION, 'preparation_receipt_sha256': receipt_sha256,
                                     'preparation_code_sha256': '1' * 64,
                                     'native_sampling': 'irregular-original-soundings',
                                     'grid_spacing_m': 5, 'minimum_good_soundings': 3}}

    def valid(self):
        return members(receipt_fields(sha(SOURCE_BYTES)))

    def bound(self, data):
        """Write receipt bytes and bind their recomputed SHA256 into a fresh row."""
        path = self.fresh() / 'preparation.json'
        path.write_bytes(data)
        return path, self.row(sha(data))

    def assert_strict_refusal(self, data):
        """THE regression assertion: an ambiguous receipt is refused under the strict decoder."""
        path, row = self.bound(data)
        with self.assertRaises(ValueError) as caught:
            self.mg.reviewed_receipt(path, row)
        self.assertIn(STRICT, str(caught.exception))

    def assert_accepts(self, data):
        path, row = self.bound(data)
        receipt = self.mg.reviewed_receipt(path, row)
        self.assertEqual(typed(receipt), typed(json.loads(data)))
        return receipt

    def duplicate_cases(self):
        v = self.valid()
        h = json.dumps(sha(SOURCE_BYTES))
        a, other = json.dumps('a' * 64), json.dumps('9' * 64)
        parity = json.dumps('private-multibeam-grid-parity')
        return [
            ('dup-output_sha256-identical', render(v + [('"output_sha256"', h)])),
            ('dup-output_sha256-last-wins-valid',
             render(replaced(v, 'output_sha256', json.dumps('0' * 64)) + [('"output_sha256"', h)])),
            ('dup-output_sha256-unicode-escaped', render(v + [('"output\\u005fsha256"', h)])),
            ('dup-source_qualified-identical', render(v + [('"source_qualified"', 'false')])),
            ('dup-source_qualified-true-then-false',
             render(replaced(v, 'source_qualified', 'true') + [('"source_qualified"', 'false')])),
            ('dup-source_qualified-unicode-escaped', render(v + [('"source\\u005fqualified"', 'false')])),
            ('dup-originals-key-identical',
             render(replaced(v, 'originals', '{"original.mb57": %s, "original.mb57": %s}' % (a, a)))),
            ('dup-originals-key-different-hashes',
             render(replaced(v, 'originals', '{"original.mb57": %s, "original.mb57": %s}' % (other, a)))),
            ('dup-originals-key-unicode-escaped',
             render(replaced(v, 'originals', '{"original.mb57": %s, "original\\u002emb57": %s}' % (a, a)))),
            ('dup-depth3-extra-map', render(v + [('"review"', '{"checks": {"state": 1, "state": 1}}')])),
            ('dup-object-inside-list', render(v + [('"review_list"', '[{"state": 1, "state": 1}]')])),
            ('dup-scope-fully-escaped', render(v + [('"\\u0073\\u0063\\u006f\\u0070\\u0065"', parity)])),
        ]

    # ------------------------------------------------------------ regression

    def test_regression(self):
        v = self.valid()
        for label, data in self.duplicate_cases():
            with self.case(label):
                self.assert_strict_refusal(data)
        for name, token in self.fixture['nonfinite_tokens'].items():
            for position, data in (
                    ('top-extra', render(v + [('"diagnostic_metric"', token)])),
                    ('nested-extra', render(v + [('"review"', '{"metrics": [1, %s]}' % token)])),
                    ('semantic-spacing', render(replaced(v, 'derived_bin_spacing_m', token)))):
                with self.case('nonfinite-%s-%s' % (name, position)):
                    self.assert_strict_refusal(data)
        with self.case('overflow-integer-5001-digits'):
            self.assert_strict_refusal(render(v + [('"diagnostic_count"', '1' + '0' * 5000)]))
        for name, text in self.fixture['top_level'].items():
            with self.case('top-level-' + name):
                self.assert_strict_refusal(text.encode())
        with self.case('top-level-list-of-valid-receipt'):
            self.assert_strict_refusal(b'[' + render(v) + b']')
        for name, text in self.fixture['malformed'].items():
            with self.case('malformed-' + name):
                self.assert_strict_refusal(text.encode())
        with self.case('malformed-invalid-utf8'):
            self.assert_strict_refusal(b'{"scope": "\xff"}')
        duplicate = self.duplicate_cases()[0][1]
        with self.case('hash-mismatch-fails-before-decoding'):
            path, _ = self.bound(duplicate)
            row = self.row(sha(render(v)))
            spy = JsonSpy()
            with patch.object(self.mg, 'json', spy), self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                self.mg.reviewed_receipt(path, row)
            self.assertEqual(spy.calls, 0)
        with self.case('byte-bound-fails-before-decoding'):
            data = render(v) + b' ' * 1_000_001
            path, row = self.bound(data)
            spy = JsonSpy()
            with patch.object(self.mg, 'json', spy), self.assertRaisesRegex(ValueError, 'exceeds bound'):
                self.mg.reviewed_receipt(path, row)
            self.assertEqual(spy.calls, 0)
        with self.case('missing-receipt-fails-before-decoding'):
            row = self.row(sha(render(v)))
            spy = JsonSpy()
            with patch.object(self.mg, 'json', spy), self.assertRaisesRegex(ValueError, 'missing or exceeds'):
                self.mg.reviewed_receipt(self.fresh() / 'absent.json', row)
            self.assertEqual(spy.calls, 0)
        with self.case('source-files-local-duplicate-sidecar'):
            folder = self.fresh(); local = folder / 'grid.tif'; local.write_bytes(SOURCE_BYTES)
            local.with_suffix('.json').write_bytes(duplicate)
            with self.assertRaises(ValueError) as caught:
                self.mg.source_files(self.row(sha(duplicate)), folder / 'cache', local)
            self.assertIn(STRICT, str(caught.exception))
        with self.case('source-files-cached-duplicate-pair'):
            folder = self.fresh(); pair = folder / 'cache' / sha(SOURCE_BYTES); pair.mkdir(parents=True)
            (pair / 'source.tif').write_bytes(SOURCE_BYTES); (pair / 'preparation.json').write_bytes(duplicate)
            with self.assertRaises(ValueError) as caught:
                self.mg.source_files(self.row(sha(duplicate)), folder / 'cache', None)
            self.assertIn(STRICT, str(caught.exception))
        self.finish()

    # ------------------------------------------------------------ compatibility

    def test_compatibility(self):
        fields = receipt_fields(sha(SOURCE_BYTES))
        v = self.valid()
        variants = [
            ('compact', json.dumps(fields, separators=(',', ':')).encode()),
            ('default-dumps', json.dumps(fields).encode()),
            ('indent-2', json.dumps(fields, indent=2).encode()),
            ('indent-4-sorted', json.dumps(fields, indent=4, sort_keys=True).encode()),
            ('reversed-key-order', json.dumps(dict(reversed(list(fields.items())))).encode()),
            ('crlf-tabs', json.dumps(fields, indent='\t').replace('\n', '\r\n').encode()),
            ('surrounding-whitespace', b' \n\t' + json.dumps(fields).encode() + b'\r\n '),
            ('utf8-bom', b'\xef\xbb\xbf' + json.dumps(fields).encode()),
            ('spacing-int-5', render(replaced(v, 'derived_bin_spacing_m', '5'))),
            ('spacing-float-5.0', render(replaced(v, 'derived_bin_spacing_m', '5.0'))),
            ('spacing-exponent-5e0', render(replaced(v, 'derived_bin_spacing_m', '5e0'))),
            ('spacing-exponent-50e-1', render(replaced(v, 'derived_bin_spacing_m', '50E-1'))),
            ('counts-float-zero', render(replaced(replaced(v, 'new_measured_km2', '0.0'),
                                                  'count_support_mismatches', '0.0'))),
            ('counts-negative-zero', render(replaced(replaced(v, 'new_public_locations', '-0'),
                                                     'new_measured_km2', '-0.0'))),
            ('escaped-distinct-value', render(replaced(v, 'scope', '"private\\u002dmultibeam-grid-parity"'))),
            ('case-distinct-extra-key', render(v + [('"Output_sha256"', json.dumps('0' * 64))])),
            ('same-key-in-different-objects',
             render(v + [('"review"', '{"scope": "other", "originals": {"original.mb57": 1}}')])),
            ('eight-originals', render(replaced(replaced(
                v, 'originals', json.dumps({'original-%d.mb57' % i: '%x' % i * 64 for i in range(8)})),
                'beam_table_sha256', json.dumps(['b' * 64] * 8)))),
            ('non-ascii-extra-key', render(v + [('"note_\u00e9"', '"r\u00e9sum\u00e9"')])),
        ]
        for label, data in variants:
            with self.case('valid-' + label):
                self.assert_accepts(data)
        refusals = [
            ('source-qualified-true', replaced(v, 'source_qualified', 'true'), SEMANTICS),
            ('exportable-true', replaced(v, 'exportable', 'true'), SEMANTICS),
            ('wrong-output-sha256', replaced(v, 'output_sha256', json.dumps('0' * 64)), SEMANTICS),
            ('new-public-location', replaced(v, 'new_public_locations', '1'), SEMANTICS),
            ('original-hash-not-hex', replaced(v, 'originals', '{"original.mb57": "not-a-hash"}'), PROVENANCE),
            ('table-count-mismatch', replaced(v, 'beam_table_sha256', json.dumps(['b' * 64] * 2)), PROVENANCE),
        ]
        for label, raw, message in refusals:
            with self.case('existing-refusal-' + label):
                path, row = self.bound(render(raw))
                with self.assertRaisesRegex(ValueError, message):
                    self.mg.reviewed_receipt(path, row)
        data = json.dumps(fields, indent=2).encode()
        with self.case('source-files-local-paired-import'):
            folder = self.fresh(); local = folder / 'grid.tif'; local.write_bytes(SOURCE_BYTES)
            local.with_suffix('.json').write_bytes(data)
            source, receipt = self.mg.source_files(self.row(sha(data)), folder / 'cache', local)
            self.assertEqual(source, folder / 'cache' / sha(SOURCE_BYTES) / 'source.tif')
            self.assertEqual(source.read_bytes(), SOURCE_BYTES)
            self.assertEqual((source.parent / 'preparation.json').read_bytes(), data)
            self.assertEqual(typed(receipt), typed(json.loads(data)))
        with self.case('source-files-cached-pair-reread'):
            source, receipt = self.mg.source_files(self.row(sha(data)), folder / 'cache', None)
            self.assertEqual(typed(receipt), typed(json.loads(data)))
            self.assertEqual(sorted(p.name for p in source.parent.iterdir()), ['preparation.json', 'source.tif'])
        self.finish()

    # ------------------------------------------------------------ deciding negative control

    def test_negative_control(self):
        control = self.__class__.control
        cases = self.duplicate_cases()
        control['expected'] = [label for label, _ in cases]
        positive = json.dumps(receipt_fields(sha(SOURCE_BYTES)), indent=2).encode()
        detected = []
        with patch.object(self.mg, '_decode_receipt', ordinary_json_loads):
            for label, data in cases:
                with self.case('control-' + label):
                    try:
                        self.assert_strict_refusal(data)
                    except self.failureException as exc:
                        # Only unexpected acceptance (all digests/semantics valid) counts.
                        control['inner_failures'][label] = str(exc)
                        if str(exc) == 'ValueError not raised':
                            detected.append(label)
                        else:
                            self.fail('control failed for an unrelated reason: ' + label)
                    else:
                        self.fail('ordinary json.loads control was not detected: ' + label)
            with self.case('control-valid-positive'):
                self.assert_accepts(positive)
        control['detected'] = detected
        with self.case('control-restored'):
            self.assertIs(self.mg._decode_receipt, self.genuine)
            self.assertIsNotNone(self.genuine)
        for label, data in cases:
            with self.case('restored-' + label):
                self.assert_strict_refusal(data)
        with self.case('restored-valid-positive'):
            self.assert_accepts(positive)
        control['restored'] = self.mg._decode_receipt is self.genuine
        self.finish()

    # ------------------------------------------------------------ preservation

    def test_preservation(self):
        v = self.valid()
        duplicate = self.duplicate_cases()[4][1]
        refusals = [data for _, data in self.duplicate_cases()] + [
            render(v + [('"diagnostic_metric"', t)]) for t in self.fixture['nonfinite_tokens'].values()]
        with self.case('receipt-bytes-unchanged-on-refusal'):
            for data in refusals:
                path, row = self.bound(data)
                with self.assertRaises(ValueError):
                    self.mg.reviewed_receipt(path, row)
                self.assertEqual(path.read_bytes(), data)
        with self.case('row-unchanged-on-refusal'):
            path, row = self.bound(duplicate)
            before = typed(deepcopy(row))
            with self.assertRaises(ValueError):
                self.mg.reviewed_receipt(path, row)
            self.assertEqual(typed(row), before)
        folder = self.fresh(); local = folder / 'grid.tif'; local.write_bytes(SOURCE_BYTES)
        local.with_suffix('.json').write_bytes(duplicate)
        row = self.row(sha(duplicate))
        with self.case('local-refusal-publishes-no-cache-pair'):
            with self.assertRaises(ValueError):
                self.mg.source_files(row, folder / 'cache', local)
            self.assertFalse((folder / 'cache').exists())
        with self.case('local-refusal-inputs-unchanged'):
            self.assertEqual(local.read_bytes(), SOURCE_BYTES)
            self.assertEqual(local.with_suffix('.json').read_bytes(), duplicate)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['grid.json', 'grid.tif'])
        with self.case('refusal-does-not-qualify-source'):
            self.assertEqual(typed(row), typed(self.row(sha(duplicate))))
            self.assertNotIn('adapter_review', row)
            self.assertEqual(row['status'], 'candidate')
        cached = self.fresh(); pair = cached / 'cache' / sha(SOURCE_BYTES); pair.mkdir(parents=True)
        (pair / 'source.tif').write_bytes(SOURCE_BYTES); (pair / 'preparation.json').write_bytes(duplicate)
        with self.case('cached-pair-bytes-unchanged-on-refusal'):
            with self.assertRaises(ValueError):
                self.mg.source_files(self.row(sha(duplicate)), cached / 'cache', None)
            self.assertEqual((pair / 'source.tif').read_bytes(), SOURCE_BYTES)
            self.assertEqual((pair / 'preparation.json').read_bytes(), duplicate)
        with self.case('cached-refusal-adds-no-files'):
            self.assertEqual(sorted(p.name for p in pair.iterdir()), ['preparation.json', 'source.tif'])
        with self.case('valid-receipt-bytes-unchanged-after-accept'):
            data = json.dumps(receipt_fields(sha(SOURCE_BYTES))).encode()
            path, row = self.bound(data)
            self.mg.reviewed_receipt(path, row)
            self.assertEqual(path.read_bytes(), data)
        with self.case('temporary-files-only-under-invocation-root'):
            parts = [p for p in self.run_root.rglob('*.part')]
            self.assertEqual(parts, [])
            self.assertEqual(self.guard.events, [])
        with self.case('no-network-model-or-child'):
            for target in ('socket.create_connection', 'subprocess.Popen', 'os.system'):
                module, name = target.rsplit('.', 1)
                self.assertEqual(getattr(importlib.import_module(module), name), self.guard.refuse)
            self.assertEqual(self.guard.events, [])
        with self.case('decoder-and-module-constants-unchanged'):
            self.assertIs(self.mg._decode_receipt, self.genuine)
            self.assertEqual(typed((self.mg.FORMAT, self.mg.VERSION, self.mg.DESCRIPTIONS)), self.constants)
        with self.case('patches-restored'):
            self.assertIs(builtins.open, self.patched['open'])
            self.assertIs(io.open, self.patched['io.open'])
            self.assertIs(subprocess.Popen, self.patched['popen'])
            self.assertIs(socket.socket.connect, self.patched['connect'])
            self.assertIs(os.system, self.patched['system'])
            self.assertIs(self.mg.json, json)
            self.assertIs(self.mg.shutil, shutil)
        with self.case('product-origin-is-candidate'):
            self.assertTrue(Path(self.mg.__file__).resolve().is_relative_to(REPO / 'src'))
            self.assertEqual(self.origins[MODULE],
                             str((REPO / 'src/skippercast/seafloor/adapters/multibeam_grid.py').resolve()))
        self.finish()


class ZPeerAfterTests(unittest.TestCase):
    """Harmless peer that runs after the SC172 class: same environment and patch state."""

    def test_peer(self):
        after = load_support().peer_state()
        self.assertNotIn(MODULE, sys.modules)
        if 'before' in PEER:
            self.assertEqual(after, PEER['before'])


if __name__ == '__main__':
    unittest.main()

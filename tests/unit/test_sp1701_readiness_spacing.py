"""SP-17-v1 / SP1701: synthetic integration tests for the real readiness compiler.

The bundle mirrors compile_readiness's input closure, not a copied algorithm.
Imports and sentinels are scoped to each call, including under peer discovery.
"""
from contextlib import contextmanager, ExitStack
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/sp1701_readiness_spacing/root-inputs.json'
CANDIDATE = 'catalog/candidates/synthetic-grid.json'
SECTOR = 'synthetic-sector-00'
FINE = 'accessible_inspected_fine_source_candidate_ids'
DEEP = 'native_depth_excluded_source_candidate_ids'


def forbidden(*args, **kwargs):
    raise RuntimeError('SP1701 offline boundary: network/model/process/live-store access forbidden')


@contextmanager
def isolated_readiness(root):
    """Execute complete staged modules without rebinding ambient peer modules.

    paths.repo_root reads the fixture root before contracts.REPO and the compiler's
    bound default are created. Every source module comes from this clone. The
    actual JSON reader/writer remains in use (except the explicit NaN seam).
    """
    previous = {k: v for k, v in sys.modules.items()
                if k == 'skippercast' or k.startswith('skippercast.')}
    old_path = sys.path[:]
    for name in previous:
        del sys.modules[name]
    try:
        with ExitStack() as guards:
            guards.enter_context(mock.patch.dict(os.environ, {'SKIPPERCAST_ROOT': str(root)}))
            guards.enter_context(mock.patch.object(socket.socket, 'connect', forbidden))
            guards.enter_context(mock.patch.object(socket, 'create_connection', forbidden))
            guards.enter_context(mock.patch.object(urllib.request, 'urlopen', forbidden))
            guards.enter_context(mock.patch.object(subprocess, 'Popen', forbidden))
            guards.enter_context(mock.patch.object(sqlite3, 'connect', forbidden))
            sys.path.insert(0, str(ROOT / 'src'))
            module = importlib.import_module('skippercast.platform.readiness')
            if Path(module.__file__).resolve() != ROOT / 'src/skippercast/platform/readiness.py':
                raise RuntimeError('Readiness import escaped the staged clone')
            if module.compile_readiness.__defaults__ != (root,):
                raise RuntimeError('Readiness default was not redirected before import')
            yield module
    finally:
        for name in list(sys.modules):
            if name == 'skippercast' or name.startswith('skippercast.'):
                del sys.modules[name]
        sys.modules.update(previous)
        sys.path[:] = old_path


class FixtureCase(unittest.TestCase):
    def setUp(self):
        output = Path(os.environ.get('SP1701_TEST_OUTPUT', ROOT / 'build/sp1701-tests'))
        output.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix='case-', dir=output))
        self.inputs = json.loads(FIXTURE.read_text())

    def materialize(self):
        root = Path(tempfile.mkdtemp(prefix='root-', dir=self.work))
        links = {
            'dist/data/nbs-hard-footprint-depth-audit.json': {
                'inventory_sha256': 'dist/data/nbs-hard-footprint-tile-inventory.json'},
            'dist/data/nbs-hard-footprint-original-class-overlap.json': {
                'depth_audit_sha256': 'dist/data/nbs-hard-footprint-depth-audit.json'},
            'dist/data/usgs-ds781-character-semantics.json': {
                'source_native_audit_sha256': 'dist/data/usgs-ds781-native-character-review.json',
                'source_metadata_inventory_sha256': 'catalog/usgs-ds781-metadata-review.json'},
        }
        for relative, packet in self.inputs.items():
            packet = copy.deepcopy(packet)
            for key, source in links.get(relative, {}).items():
                packet[key] = hashlib.sha256((root / source).read_bytes()).hexdigest()
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(packet, allow_nan=False) + '\n')
        return root

    def compile(self, resolution=4, *, candidate=None, nan_seam=False):
        row = self.inputs[CANDIDATE]
        row['spatial']['resolution_m'] = resolution
        if candidate is not None:
            self.inputs[CANDIDATE] = candidate
        root = self.materialize()
        with isolated_readiness(root) as module:
            if nan_seam:
                # Strict JSON rejects the NaN token. Inject just this unreachable
                # numeric value at the reader seam to qualify the full predicate.
                actual_reader = module.read_json
                def read(path):
                    value = actual_reader(path)
                    if Path(path) == root / CANDIDATE:
                        value['spatial']['resolution_m'] = float('nan')
                    return value
                with mock.patch.object(module, 'read_json', side_effect=read):
                    module.compile_readiness()
            else:
                module.compile_readiness()
        return json.loads((root / 'dist/data/california-atlas-readiness.json').read_text())

    def first(self, report):
        return next(row for row in report['sectors'] if row['sector_id'] == SECTOR)


class BaselineTests(FixtureCase):
    def test_primary_regression(self):
        self.assertNotIn('synthetic-grid', self.first(self.compile(0))[FINE],
                         'SP1701_A1_ZERO_SPACING_MUST_NOT_BECOME_FINE_LEAD')

    def test_healthy_control(self):
        self.assertEqual(self.first(self.compile(4))[FINE], ['synthetic-grid'])


class AcceptanceTests(FixtureCase):
    def test_a2_numeric_domain_and_threshold(self):
        for value in (-1, -0.0, -0.25, True, False, None, '4', 10.000001,
                      11, 10 ** 400):
            with self.subTest(resolution=repr(value)):
                self.assertEqual(self.first(self.compile(value))[FINE], [])
        for value in (4, 4.0, 10, 10.0, 0.000001):
            with self.subTest(resolution=value):
                self.assertEqual(self.first(self.compile(value))[FINE], ['synthetic-grid'])
        for token in ('1e999', '-1e999'):
            with self.subTest(json_number=token):
                root = self.materialize()
                path = root / CANDIDATE
                current = json.dumps(self.inputs[CANDIDATE]['spatial']['resolution_m'])
                text = path.read_text().replace(f'"resolution_m": {current}', f'"resolution_m": {token}')
                self.assertIn(f'"resolution_m": {token}', text)
                path.write_text(text)
                with isolated_readiness(root) as module:
                    module.compile_readiness()
                report = json.loads((root / 'dist/data/california-atlas-readiness.json').read_text())
                self.assertEqual(self.first(report)[FINE], [])
        self.assertEqual(self.first(self.compile(4, nan_seam=True))[FINE], [])

    def test_a3_source_eligibility_and_depth_exclusion(self):
        pristine = copy.deepcopy(self.inputs[CANDIDATE])
        for field, value in (('access_status', 'inaccessible'), ('resolution_basis', 'catalog'),
                             ('bounds', []), ('need_ids', ['temperature'])):
            with self.subTest(field=field):
                row = copy.deepcopy(pristine)
                (row['spatial'] if field in ('resolution_basis', 'bounds') else row)[field] = value
                first = self.first(self.compile(candidate=row))
                self.assertEqual(first[FINE], [])
                self.assertEqual(first[DEEP], [])
        row = copy.deepcopy(pristine)
        row['spatial']['native_depth_screen'] = {'limit_ft': 200, 'cells_within_limit': 0}
        first = self.first(self.compile(candidate=row))
        self.assertEqual(first[FINE], [])
        self.assertEqual(first[DEEP], ['synthetic-grid'])
        row['spatial']['native_depth_screen']['cells_within_limit'] = 1
        first = self.first(self.compile(candidate=row))
        self.assertEqual(first[FINE], ['synthetic-grid'])
        self.assertEqual(first[DEEP], [])

    def test_a4_complete_shapes_policy_and_validation_preserved(self):
        report = self.compile(4)
        self.assertEqual(len(report['sectors']), 19)
        self.assertEqual({r['sector_id'] for r in report['sectors']},
                         {r['id'] for r in self.inputs['dist/data/coastal-sectors.json']['sectors']})
        self.assertEqual(report, self.compile(10))
        for row in report['sectors']:
            self.assertEqual(row['status'], 'source-review-only')
            self.assertEqual(row['published_candidate_points_in_band'], 0)
            self.assertEqual(len(row['remaining_promotion_gates']), 6)
            self.assertTrue(row['nbs_original_hard_footprint_screen']['research_only'])
        self.assertIn('chart datum and uncertainty', self.first(report)['next_source_step'])
        # The same inputs without the lead retain all other report policy fields.
        zero = self.compile(0)
        no_lead = copy.deepcopy(self.inputs[CANDIDATE])
        no_lead['access_status'] = 'inaccessible'
        self.assertEqual(zero, self.compile(candidate=no_lead))
        self.inputs['dist/data/noaa-native-sector-review.json']['sectors'].pop()
        with self.assertRaisesRegex(ValueError, 'missing or has duplicate sectors'):
            self.compile(4)

    def test_a4_unknown_sector_still_rejected(self):
        self.inputs[CANDIDATE]['sector_ids'] = ['unknown-sector']
        with self.assertRaisesRegex(ValueError, 'Unknown sector for original-grid candidate'):
            self.compile(4)

    def test_a4_nonstandard_json_nan_still_rejected(self):
        root = self.materialize()
        path = root / CANDIDATE
        path.write_text(path.read_text().replace('"resolution_m": 4', '"resolution_m": NaN'))
        with isolated_readiness(root) as module:
            with self.assertRaisesRegex(ValueError, 'Non-finite JSON number: NaN'):
                module.compile_readiness()

    def test_import_boundary_restores_peer_state(self):
        before = {k: v for k, v in sys.modules.items()
                  if k == 'skippercast' or k.startswith('skippercast.')}
        old_path = sys.path[:]
        original_connect = socket.socket.connect
        self.compile(4)
        self.assertEqual(before, {k: v for k, v in sys.modules.items()
                                 if k == 'skippercast' or k.startswith('skippercast.')})
        self.assertEqual(old_path, sys.path)
        self.assertIs(socket.socket.connect, original_connect)


if __name__ == '__main__':
    unittest.main()

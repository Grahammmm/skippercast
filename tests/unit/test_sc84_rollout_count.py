"""SC84: rollout.plan refuses a non-integer max_new before it reads any input.

The tests call the real skippercast.seafloor.rollout.plan against a small synthetic
planning tree built from tests/fixtures/sc84-rollout-count/fixture.json in a fresh
temporary directory. Spies wrap (never replace) the module's own ledger reader,
reference hasher and geometry helpers, so the call order is observed while the
real implementation runs. The survey manifest is supplied through a patched
load_manifest, as in tests/gis/test_seafloor_rollout.py. Every test appends
before/after byte hashes of its synthetic tree and the authored fixture to EVIDENCE.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import rollout
from skippercast.seafloor.io import sha256

FIXTURE = Path(__file__).resolve().parents[1]/'fixtures/sc84-rollout-count/fixture.json'
EVIDENCE = []

# Assertion class per test method, reported by tools/run_sc84_rollout_count.py.
ASSERTION_CLASSES = {
    'test_zero_count_is_maintenance_mode': 'positive',
    'test_one_count_selects_top_reach': 'positive',
    'test_default_count_is_three_with_tie_order': 'positive',
    'test_exact_reach_count_is_inclusive_bound': 'positive',
    'test_region_filters_and_processed_refresh_unchanged': 'positive',
    'test_bool_count_refused_before_ledger_read': 'negative-early-refusal',
    'test_noninteger_counts_refused_before_ledger_read': 'negative-early-refusal',
    'test_out_of_range_integers_refused_before_manifest_reference_geometry': 'negative-bound-after-ledger',
    'test_reviewed_window_fixture_counts': 'compatibility',
}

# Values that are not a Python int (or are a bool) and must never reach the ledger.
NONINTEGER_COUNTS = (True, False, 0.0, 1.0, 3.0, 1.5, -0.5, float('nan'), float('inf'),
                     float('-inf'), '1', '', None, [], [1], (1,), {}, {'n': 1}, {1})


def tree_digest(root):
    """Hash every file path and its bytes below root, in a stable order."""
    h = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob('*') if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode()+b'\0')
        h.update(path.read_bytes()+b'\0')
    return h.hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_tree(root, spec=None):
    """Write the synthetic ledger, reference cells and screen catalog; return the survey rows."""
    spec = spec or json.loads(FIXTURE.read_text())
    root = Path(root)
    ref = root/'var/seafloor/reference/cells.json'
    atomic_json(ref, {'cells': spec['cells']})
    atomic_json(root/'dist/data/seafloor-ledger.json', {'scope': spec['scope'],
        'reference_cells_sha256': sha256(ref), 'totals': {}, 'reaches': spec['reaches']})
    atomic_json(root/'catalog/seafloor-screen.json', {'reviewed_reaches': spec['reviewed_reaches']})
    t = Transformer.from_crs(3310, 4326, always_xy=True)
    x0, y0, x1, y1 = spec['source_bounds_epsg3310']
    bounds = [*t.transform(x0, y0), *t.transform(x1, y1)]
    surveys = [dict(r) for r in spec['surveys']]
    for row in surveys:
        if row['status'] == 'usable':
            row['adapter_review'] = {'requested_bounds_wgs84': bounds}
    return surveys


class SyntheticTree(unittest.TestCase):
    spec = None
    prefix = 'sc84-'

    def setUp(self):
        self.fixture_before = file_digest(FIXTURE)
        self._tmp = tempfile.TemporaryDirectory(prefix=self.prefix)
        self.root = Path(self._tmp.name)/'repo'
        self.surveys = build_tree(self.root, self.spec)
        self.manifest = patch.object(rollout, 'load_manifest',
                                     return_value={'surveys': self.surveys})
        self.load_manifest = self.manifest.start()
        self.before = tree_digest(self.root)

    def tearDown(self):
        self.manifest.stop()
        after = tree_digest(self.root)
        EVIDENCE.append({'test': self.id(), 'synthetic_tree_before': self.before,
                         'synthetic_tree_after': after, 'tree_unchanged': after == self.before,
                         'fixture_before': self.fixture_before, 'fixture_after': file_digest(FIXTURE)})
        self._tmp.cleanup()

    def assertTreeUnchanged(self):
        self.assertEqual(tree_digest(self.root), self.before)
        self.assertEqual(file_digest(FIXTURE), self.fixture_before)

    def spies(self):
        """Wrap the real input readers so calls are observed but behavior is unchanged."""
        return (patch.object(rollout, 'read_json', wraps=rollout.read_json),
                patch.object(rollout, 'sha256', wraps=rollout.sha256),
                patch.object(rollout, 'Transformer', wraps=rollout.Transformer),
                patch.object(rollout, 'cell_geometry', wraps=rollout.cell_geometry))

    def assertNoInputRead(self, value):
        self.load_manifest.reset_mock()
        read, digest, transformer, geometry = self.spies()
        with read as read_json, digest as hasher, transformer as crs, geometry as cells:
            with self.assertRaisesRegex(ValueError, 'max_new'):
                rollout.plan(self.root, max_new=value)
            read_json.assert_not_called()
            self.load_manifest.assert_not_called()
            hasher.assert_not_called()
            crs.from_crs.assert_not_called()
            cells.assert_not_called()
        self.assertTreeUnchanged()


class RolloutCountTests(SyntheticTree):
    def test_zero_count_is_maintenance_mode(self):
        result = rollout.plan(self.root, max_new=0)
        self.assertEqual(result['new_reaches'], [])
        self.assertEqual(result['selected'], [{'reach': 'r04', 'region': 'south'}])
        self.assertFalse(result['execution']['new_reach_batch_selected'])
        self.assertEqual(result['execution']['next_action'], 'inspect-native-gaps')
        self.assertEqual(result['execution']['refresh_reaches'], ['r04'])
        self.assertIsNone(result['execution']['additional_measured_km2'])
        self.assertTreeUnchanged()

    def test_one_count_selects_top_reach(self):
        result = rollout.plan(self.root, max_new=1)
        self.assertEqual(result['new_reaches'], ['r01'])
        self.assertEqual(result['selected'], [{'reach': 'r04', 'region': 'south'},
                                              {'reach': 'r01', 'region': 'central'}])
        self.assertTrue(result['execution']['new_reach_batch_selected'])
        self.assertEqual(result['execution']['next_action'], 'process-reviewed-batch')
        self.assertIsNone(result['execution']['additional_measured_km2'])
        self.assertTreeUnchanged()

    def test_default_count_is_three_with_tie_order(self):
        result = rollout.plan(self.root)
        # r02 and r03 tie on estimate; the reach id breaks the tie, not ledger order.
        self.assertEqual(result['new_reaches'], ['r01', 'r02', 'r03'])
        self.assertEqual(rollout.plan(self.root, max_new=3)['new_reaches'], ['r01', 'r02', 'r03'])
        self.assertEqual([r['reach'] for r in result['reaches']],
                         ['r06', 'r03', 'r01', 'r04', 'r02', 'r05'])
        self.assertEqual([r['action'] for r in result['reaches']],
                         ['compute', 'compute', 'compute', 'refresh', 'compute', 'qualify-source'])
        self.assertEqual([r['reviewed_window_band_estimate_km2'] for r in result['reaches']],
                         [0.04, 0.05, 0.06, 0.07, 0.05, 0.0])
        self.assertIsNone(result['execution']['additional_measured_km2'])
        self.assertEqual(len(result['source_review_queue']), 1)
        self.assertTreeUnchanged()

    def test_exact_reach_count_is_inclusive_bound(self):
        result = rollout.plan(self.root, max_new=6)
        self.assertEqual(result['new_reaches'], ['r01', 'r02', 'r03', 'r06'])
        self.assertEqual([r['reach'] for r in result['selected']], ['r04', 'r01', 'r02', 'r03', 'r06'])
        self.assertIsNone(result['execution']['additional_measured_km2'])
        self.assertTreeUnchanged()

    def test_region_filters_and_processed_refresh_unchanged(self):
        south = rollout.plan(self.root, region='south', max_new=1)
        self.assertEqual(south['scope'], 'south')
        self.assertEqual([r['reach'] for r in south['reaches']], ['r04', 'r05'])
        self.assertEqual(south['new_reaches'], [])
        self.assertEqual(south['selected'], [{'reach': 'r04', 'region': 'south'}])
        self.assertEqual(south['execution']['refresh_reaches'], ['r04'])
        self.assertTrue(south['reaches'][0]['screen_reviewed'])
        central = rollout.plan(self.root, region='central', max_new=2)
        self.assertEqual(central['new_reaches'], ['r01', 'r02'])
        self.assertEqual(central['execution']['refresh_reaches'], [])
        whole = rollout.plan(self.root, region='central-coast', max_new=2)
        self.assertEqual(whole['new_reaches'], ['r01', 'r02'])
        self.assertEqual(whole['execution']['refresh_reaches'], ['r04'])
        advanced = rollout.plan(self.root, max_new=1, progress={'r01': {'status': 'complete'}})
        self.assertEqual(advanced['new_reaches'], ['r02'])
        self.assertEqual(advanced['execution']['refresh_reaches'], ['r01', 'r04'])
        self.assertTrue(advanced['reaches'][2]['pending_ledger_merge'])
        self.assertEqual(advanced['reaches'][2]['tier1_km2'], 0)
        for document in (south, central, whole, advanced):
            self.assertIsNone(document['execution']['additional_measured_km2'])
        self.assertTreeUnchanged()

    def test_bool_count_refused_before_ledger_read(self):
        for value in (True, False):
            with self.subTest(value=value):
                self.assertNoInputRead(value)

    def test_noninteger_counts_refused_before_ledger_read(self):
        for value in NONINTEGER_COUNTS:
            with self.subTest(value=repr(value)):
                self.assertNoInputRead(value)

    def test_out_of_range_integers_refused_before_manifest_reference_geometry(self):
        for value in (-1, -3, 7, 10**6):
            with self.subTest(value=value):
                self.load_manifest.reset_mock()
                read, digest, transformer, geometry = self.spies()
                with read as read_json, digest as hasher, transformer as crs, geometry as cells:
                    with self.assertRaisesRegex(ValueError, 'max_new'):
                        rollout.plan(self.root, max_new=value)
                    read_json.assert_called_once_with(self.root/'dist/data/seafloor-ledger.json')
                    self.load_manifest.assert_not_called()
                    hasher.assert_not_called()
                    crs.from_crs.assert_not_called()
                    cells.assert_not_called()
                self.assertTreeUnchanged()


ORIGINAL_CELLS = [{'id': '3310:0:0', 'reach': 'r01', 'band_area_m2': 60000},
                  {'id': '3310:1:0', 'reach': 'r02', 'band_area_m2': 50000},
                  {'id': '3310:80:0', 'reach': 'r03', 'band_area_m2': 60000}]


class CompatibilityTests(SyntheticTree):
    """The reviewed-window planning tree of the original rollout test, driven only through rollout.plan."""
    prefix = 'sc84-compat-'
    spec = {'scope': 'central-coast', 'cells': ORIGINAL_CELLS, 'reviewed_reaches': [],
            'reaches': [{'id': c['reach'], 'region': 'central', 'status': 'unassessed',
                         'tier1_km2': 0, 'tier2_km2': 0} for c in ORIGINAL_CELLS],
            'source_bounds_epsg3310': [-10, -10, 600, 260],
            'surveys': [{'id': 'native', 'status': 'usable', 'kind': 'bathymetry'},
                        {'id': 'envelope', 'kind': 'bathymetry', 'status': 'candidate',
                         'publisher': 'NOAA', 'title': 'unverified',
                         'url': 'https://example.org/data', 'hold_reason': 'unknown'}]}

    def test_reviewed_window_fixture_counts(self):
        self.assertEqual(rollout.plan(self.root, max_new=1)['new_reaches'], ['r01'])
        self.assertEqual(rollout.plan(self.root, max_new=0)['new_reaches'], [])
        self.assertEqual(rollout.plan(self.root)['new_reaches'], ['r01', 'r02'])
        exact = rollout.plan(self.root, max_new=3)
        self.assertEqual(exact['new_reaches'], ['r01', 'r02'])
        self.assertEqual(exact['reaches'][2]['action'], 'qualify-source')
        self.assertTrue(all(r['tier1_km2'] == 0 for r in exact['reaches']))
        self.assertIsNone(exact['execution']['additional_measured_km2'])
        with self.assertRaisesRegex(ValueError, 'max_new'):
            rollout.plan(self.root, max_new=4)
        for value in (True, 1.0):
            with self.subTest(value=value):
                self.assertNoInputRead(value)
        self.assertTreeUnchanged()


if __name__ == '__main__':
    unittest.main()

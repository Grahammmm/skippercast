"""Known source-quality holds preserve physics and survive legal/publication stages."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import habitat, habitat_tiles, publish
from skippercast.seafloor.io import sha256
from skippercast.seafloor.screen import screen_candidates
from tests.gis.test_seafloor_habitat import fixture, RULES
from tests.gis.test_seafloor_screen import state, geo


HOLD = {'source_sha256': 'a'*64, 'reviewed_on': '2026-09-01',
        'reason': 'interpretation-conflict',
        'evidence': ['research/receipts/fixture.json#/artifact_review'],
        'notes': 'Producer terrain conflicts with automatic candidates; investigate artifacts.'}


class HabitatQualityTests(unittest.TestCase):
    def test_quality_hold_preserves_native_geometry_metrics_fit_and_selected_depth(self):
        grid = fixture()
        limits = habitat.thresholds([grid], RULES)
        reach = {'id': 'fixture', 'region': 'fixture'}
        expected = habitat.extract_grid(grid, limits, RULES, reach)
        before_depth = grid['depth'].copy(); before_valid = grid['valid'].copy()
        grid['source']['row']['habitat_quality_hold'] = deepcopy(HOLD)
        actual = habitat.extract_grid(grid, limits, RULES, reach)
        self.assertTrue(expected)
        self.assertEqual(len(actual), len(expected))
        for before, after in zip(expected, actual):
            self.assertEqual(after['geometry'], before['geometry'])
            props = deepcopy(after['properties'])
            self.assertEqual(props.pop('habitat_quality_hold'), HOLD)
            props['hold_reasons'].remove('source-habitat-quality-review')
            self.assertEqual(props, before['properties'])
        np.testing.assert_array_equal(grid['depth'], before_depth)
        np.testing.assert_array_equal(grid['valid'], before_valid)
        self.assertEqual(habitat.thresholds([grid], RULES), limits)
        with tempfile.TemporaryDirectory() as tmp, habitat_tiles.scratch(tmp) as disk:
            tiled = habitat_tiles.extract_grid(grid, limits, RULES, reach, disk, 73)
        self.assertEqual(tiled, actual)

    def test_current_legal_pass_does_not_clear_quality_hold_or_block_other_sources(self):
        grid = fixture(); limits = habitat.thresholds([grid], RULES)
        reach = {'id': 'fixture', 'region': 'fixture'}
        clear = habitat.extract_grid(grid, limits, RULES, reach)
        grid['source']['row'].update(id='quality-held', habitat_quality_hold=deepcopy(HOLD))
        needs_review = habitat.extract_grid(grid, limits, RULES, reach)
        current = state(geo(1500, 1500))
        passed, held, _ = screen_candidates({'features': clear + needs_review}, current)
        self.assertEqual(len(passed['features']), len(clear))
        self.assertEqual(len(held['features']), len(needs_review))
        for feature in held['features']:
            self.assertIn('source-habitat-quality-review', feature['properties']['hold_reasons'])
            self.assertFalse(feature['properties']['exportable'])
        # An unchanged or newly refreshed legal screen cannot erase this nonlegal hold.
        again, retained, _ = screen_candidates(held, current)
        self.assertEqual(again['features'], [])
        self.assertEqual(retained, held)

    def test_publication_rejects_quality_hold_even_if_old_output_claims_pass(self):
        for case in ('source', 'feature', 'reason'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); ref = root/'var/seafloor/reference/cells.json'
                atomic_json(ref, {'cells': []})
                atomic_json(root/'dist/data/seafloor-ledger.json', {
                    'reference_cells_sha256': sha256(ref),
                    'reaches': [{'id': 'r01', 'region': 'morro-bay', 'status': 'partial'}]})
                row = {'id': 'native'}
                if case == 'source': row['habitat_quality_hold'] = HOLD
                atomic_json(root/'catalog/surveys.json', {'surveys': [row]})
                props = {'tier': 2, 'status': 'habitat', 'exportable': True,
                         'screen': {'status': 'pass'}, 'source_ids': ['native'], 'hold_reasons': []}
                if case == 'feature': props['habitat_quality_hold'] = HOLD
                if case == 'reason': props['hold_reasons'] = ['source-habitat-quality-review']
                out = root/'var/seafloor/reaches/r01'
                atomic_json(out/'habitat.geojson', {'features': [{'properties': props}]})
                atomic_json(out/'run.json', {'inputs': {'screen': 'now'},
                    'outputs': {'habitat.geojson': sha256(out/'habitat.geojson')}})
                with patch.object(publish, 'load_snapshot', return_value={'status': 'ready'}), \
                     patch.object(publish, 'input_identity', return_value='now'):
                    with self.assertRaises(ValueError):
                        publish.region_layers(root, 'morro-bay', rerun=False)

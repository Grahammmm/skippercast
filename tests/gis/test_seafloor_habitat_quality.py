"""Known source-quality holds preserve physics and survive legal/publication stages."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import habitat, habitat_tiles, publish
from skippercast.seafloor.io import sha256
from skippercast.seafloor.coverage import classify_cells
from skippercast.seafloor.screen import screen_candidates, input_identity
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

    def test_current_legal_pass_keeps_quality_hold_without_blocking_unrelated_candidates(self):
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

    def test_shared_threshold_group_retains_indirect_source_quality_dependency(self):
        grids = [fixture(), fixture()]
        grids[1]['source']['row']['id'] = 'second'
        sources = [g['source'] for g in grids]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(habitat, 'source_grid', side_effect=grids):
            before = habitat.build_candidates(sources, [], {}, RULES, {'id': 'fixture'}, root=tmp)
        grids[1]['source']['row']['habitat_quality_hold'] = deepcopy(HOLD)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(habitat, 'source_grid', side_effect=grids):
            after = habitat.build_candidates(sources, [], {}, RULES, {'id': 'fixture'}, root=tmp)
        self.assertEqual(before['thresholds'], after['thresholds'])
        self.assertEqual(after['calibration_source_ids'], ['original', 'second'])
        self.assertEqual(len(before['features']), len(after['features']))
        self.assertTrue(any(f['properties']['source_ids'] == ['original'] for f in after['features']))
        for original, reviewed in zip(before['features'], after['features']):
            self.assertEqual(original['geometry'], reviewed['geometry'])
            p = deepcopy(reviewed['properties'])
            self.assertEqual(p.pop('habitat_quality_dependencies'), {'second': HOLD})
            p['hold_reasons'].remove('habitat-threshold-quality-review')
            if p['source_ids'] == ['second']:
                p.pop('habitat_quality_hold')
                p['hold_reasons'].remove('source-habitat-quality-review')
            self.assertEqual(p, original['properties'])
        passed, held, _ = screen_candidates(after, state(geo(1500, 1500)))
        self.assertFalse(passed['features'])
        self.assertEqual(len(held['features']), len(after['features']))

    def test_calibration_inventory_includes_selected_grid_with_no_own_candidates(self):
        grids = [fixture(), fixture()]
        grids[1]['source']['row']['id'] = 'zero-candidates'
        grids[1]['source']['row']['habitat_quality_hold'] = deepcopy(HOLD)
        sources = [g['source'] for g in grids]
        features = habitat.extract_grid(grids[0], habitat.thresholds(grids, RULES), RULES, {'id': 'fixture'})
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(habitat, 'source_grid', side_effect=grids), \
             patch.object(habitat, 'extract_grid', side_effect=[features, []]):
            result = habitat.build_candidates(sources, [], {}, RULES, {'id': 'fixture'}, root=tmp)
        self.assertEqual(result['calibration_source_ids'], ['original', 'zero-candidates'])
        self.assertTrue(result['features'])
        self.assertTrue(all(f['properties']['source_ids'] == ['original'] for f in result['features']))
        passed, held, _ = screen_candidates(result, state(geo(1500, 1500)))
        self.assertFalse(passed['features'])
        self.assertEqual(len(held['features']), len(features))

    def test_publication_rejects_quality_hold_even_if_old_output_claims_pass(self):
        for case in ('source', 'feature', 'reason', 'dependency', 'source-dependency'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); ref = root/'var/seafloor/reference/cells.json'
                atomic_json(ref, {'cells': []})
                atomic_json(root/'dist/data/seafloor-ledger.json', {
                    'reference_cells_sha256': sha256(ref),
                    'reaches': [{'id': 'r01', 'region': 'morro-bay', 'status': 'partial'}]})
                row = {'id': 'native'}
                if case == 'source': row['habitat_quality_hold'] = HOLD
                source_rows = [row]
                if case == 'source-dependency':
                    source_rows.append({'id': 'calibration-source', 'habitat_quality_hold': HOLD})
                atomic_json(root/'catalog/surveys.json', {'surveys': source_rows})
                props = {'tier': 2, 'status': 'habitat', 'exportable': True,
                         'screen': {'status': 'pass'}, 'source_ids': ['native'], 'hold_reasons': []}
                if case == 'feature': props['habitat_quality_hold'] = HOLD
                if case == 'reason': props['hold_reasons'] = ['source-habitat-quality-review']
                if case == 'dependency': props['habitat_quality_dependencies'] = {'calibration-source': HOLD}
                out = root/'var/seafloor/reaches/r01'
                atomic_json(out/'habitat.geojson', {'features': [{'properties': props}]})
                atomic_json(out/'candidates.geojson', {'calibration_source_ids': ['native', 'calibration-source']})
                atomic_json(out/'run.json', {'inputs': {'screen': 'now', 'sources': [
                    {'id': 'native'}, {'id': 'calibration-source'}]},
                    'outputs': {name: sha256(out/name) for name in ('habitat.geojson', 'candidates.geojson')}})
                with patch.object(publish, 'load_snapshot', return_value={'status': 'ready'}), \
                     patch.object(publish, 'input_identity', return_value='now'):
                    with self.assertRaises(ValueError):
                        publish.region_layers(root, 'morro-bay', rerun=False)

    def test_unselected_held_survey_does_not_block_verified_clear_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sources = []
            for ident, resolution in (('selected-fine', 2), ('unselected-coarse', 4)):
                size = 800 // resolution
                yy, xx = np.indices((size, size))
                depth = (50 - 8*np.exp(-(((xx+.5)*resolution-400)**2
                    + ((yy+.5)*resolution-400)**2)/2400)).astype('float32')
                path = root/(ident+'.tif')
                with rasterio.open(path, 'w', driver='GTiff', count=1, width=size, height=size,
                        dtype='float32', crs=3310, transform=from_origin(0, 800, resolution, resolution),
                        nodata=np.nan) as dst:
                    dst.write(depth, 1)
                row = {'id': ident, 'resolution_m': resolution, 'year': 2020, 'vertical_datum': 'unknown',
                    'license': 'public-domain-us-gov', 'url': 'https://example.org/'+ident, 'status': 'usable'}
                if ident == 'unselected-coarse': row['habitat_quality_hold'] = deepcopy(HOLD)
                sources.append({'row': row, 'path': path, 'geometry': box(0, 0, 800, 800)})
            cells = [{'id': f'3310:{x}:{y}', 'reach': 'r01', 'band_area_m2': 62500, 'tier': 0}
                     for x in range(3) for y in range(3)]
            classified = classify_cells(cells, sources)
            self.assertEqual({c['source_id'] for c in classified}, {'selected-fine'})
            self.assertIsNone(habitat.source_grid(sources[1], classified, None, root=root))
            candidates = habitat.build_candidates(sources, classified, {}, RULES,
                {'id': 'r01', 'region': 'fixture'}, root=root)
            self.assertEqual(candidates['calibration_source_ids'], ['selected-fine'])
            self.assertTrue(candidates['features'])
            current = json.loads(json.dumps(state(geo(1500, 1500))))
            for layer in current['layers']:
                layer['checked_at'] = current['snapshot']
                if layer['id'] == 'security': layer['evidence'] = {'up_to_date_as_of': '2026-09-28'}
            passed, held, _ = screen_candidates(candidates, current)
            self.assertTrue(passed['features']); self.assertFalse(held['features'])
            atomic_json(root/'catalog/surveys.json', {'surveys': [s['row'] for s in sources]})
            ref = root/'var/seafloor/reference/cells.json'
            atomic_json(ref, {'cells': cells})
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reference_cells_sha256': sha256(ref),
                'reaches': [{'id': 'r01', 'region': 'fixture', 'status': 'partial'}]})
            folder = root/'var/seafloor/reaches/r01'
            atomic_json(folder/'cells.json', {'cells': classified})
            atomic_json(folder/'habitat.geojson', passed)
            atomic_json(folder/'candidates.geojson', candidates)
            receipt = {'input_hash': 'fixture', 'ledger_summary': {},
                'inputs': {'sources': [s['row'] for s in sources], 'screen': input_identity(current)},
                'outputs': {name: sha256(folder/name) for name in
                            ('cells.json', 'habitat.geojson', 'candidates.geojson')}}
            atomic_json(folder/'run.json', receipt)
            with patch.object(publish, 'load_snapshot', return_value=current):
                layers, _, _ = publish.region_layers(root, 'fixture', rerun=False)
                self.assertEqual(len(layers['habitat']), len(passed['features']))
                # An old or malformed inventory cannot clear an unresolved hold.
                for inventory in (None, [], 'selected-fine', ['unknown'], ['selected-fine']*2):
                    with self.subTest(inventory=inventory):
                        changed = deepcopy(candidates)
                        changed['calibration_source_ids'] = inventory
                        atomic_json(folder/'candidates.geojson', changed)
                        receipt['outputs']['candidates.geojson'] = sha256(folder/'candidates.geojson')
                        atomic_json(folder/'run.json', receipt)
                        with self.assertRaisesRegex(ValueError, 'calibration inventory'):
                            publish.region_layers(root, 'fixture', rerun=False)
                # The inventory is usable only when covered by the verified receipt.
                atomic_json(folder/'candidates.geojson', candidates)
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    publish.region_layers(root, 'fixture', rerun=False)
                receipt['outputs'].pop('candidates.geojson')
                atomic_json(folder/'run.json', receipt)
                with self.assertRaisesRegex(ValueError, 'Missing verified'):
                    publish.region_layers(root, 'fixture', rerun=False)

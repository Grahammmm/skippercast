"""Original positive support restricts habitat, never measured bathymetry."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from shapely.geometry import box, shape

from skippercast.seafloor import habitat, habitat_tiles as tiled, terrain_support as support, publish
from skippercast.platform.contracts import atomic_json
from skippercast.seafloor.io import sha256
from skippercast.seafloor.adapters import arcgrid
from skippercast.seafloor import fetch
from tests.gis.test_seafloor_habitat import fixture, RULES


@contextmanager
def native_fixture(root, *, offset=0, codes=None, metadata_hash=None, depth_values=None):
    grid = fixture()
    if depth_values is not None:
        grid['depth'] = depth_values
    depth_path, classes_path = root/'depth.tif', root/'classes.tif'
    category_dir = root/'original-class'; category_dir.mkdir()
    metadata = category_dir/'metadata.xml'; metadata.write_bytes(b'<metadata>original reviewed legend</metadata>')
    codes = np.full((400, 400), -1, 'int16') if codes is None else codes
    for path, values, dtype, affine, nodata in [
            (depth_path, grid['depth'], 'float32', grid['affine'], np.nan),
            (classes_path, codes, 'int16', grid['affine']*rasterio.Affine.translation(offset, 0), -32768)]:
        with rasterio.open(path, 'w', driver='GTiff', width=400, height=400, count=1,
                dtype=dtype, crs=3310, transform=affine, nodata=nodata) as dst:
            dst.write(values, 1)
    depth_sha = hashlib.sha256(depth_path.read_bytes()).hexdigest()
    binding = {'profile': 'csumb-native-rough-v1', 'depth_source_id': 'original',
        'source_sha256': 'a'*64, 'depth_archive_member': 'native.zip/depth',
        'depth_cog_sha256': depth_sha, 'archive_member': 'habitat.zip/classes',
        'metadata_sha256': metadata_hash or hashlib.sha256(metadata.read_bytes()).hexdigest(),
        'rough_codes': list(support.ROUGH_CODES), 'smooth_codes': list(support.SMOOTH_CODES),
        'reviewed_on': '2026-01-01', 'evidence': ['catalog/test.json#/review'], 'notes': 'Same-depth rough terrain only.'}
    row = dict(grid['source']['row'], kind='bathymetry', format='arcgrid', sha256='a'*64,
        archive_member='native.zip/depth', adapter_review={'cog_sha256': depth_sha},
        evidence=binding['evidence'], terrain_support=binding)
    source = {'row': row, 'path': depth_path, 'geometry': box(0, 0, 800, 800)}
    original_open = rasterio.open
    def open_grid(path, *args, **kwargs):
        return original_open(classes_path if Path(path) == category_dir else path, *args, **kwargs)
    def original_path(archive, selected):
        return category_dir if selected['archive_member'] == binding['archive_member'] else depth_path
    with patch.object(fetch, 'fetch_source', return_value=(root/'source.tar.gz', False)), \
            patch.object(arcgrid, 'source_path', side_effect=original_path), \
            patch.object(rasterio, 'open', side_effect=open_grid):
        yield source, grid, codes


class NativeTerrainSupportTests(unittest.TestCase):
    def test_unsupported_survey_stripes_cannot_become_habitat(self):
        from pyproj import Transformer
        from shapely.ops import transform
        yy, xx = np.indices((400, 400))
        # A known synthetic acquisition artifact surrounds a real terrain bump.
        depth = (50 + .08*np.sin(xx*.5) - 8*np.exp(-((xx-200)**2+(yy-200)**2)/600)).astype('float32')
        codes = np.zeros((400, 400), 'int16'); codes[140:260, 140:260] = -1
        cells = [{'id': f'3310:{x}:{y}', 'tier': 1, 'source_id': 'original'} for x in range(4) for y in range(4)]
        with tempfile.TemporaryDirectory() as tmp, native_fixture(Path(tmp), codes=codes, depth_values=depth) as (source, _, _):
            unbound = deepcopy(source); unbound['row'].pop('terrain_support')
            before = habitat.source_grid(unbound, cells, None, root=tmp)
            after = habitat.source_grid(source, cells, None, root=tmp)
            np.testing.assert_array_equal(before['depth'], after['depth'])
            np.testing.assert_array_equal(before['valid'], after['valid'])
            for key in ('vrm', 'bpi_fine_m'):
                np.testing.assert_array_equal(before['terrain'][key], after['terrain'][key])
            original = habitat.extract_grid(before, habitat.thresholds([before], RULES), RULES, {'id': 'fixture'})
            restricted = habitat.extract_grid(after, habitat.thresholds([after], RULES), RULES, {'id': 'fixture'})
            self.assertTrue(original); self.assertTrue(restricted)
            project = Transformer.from_crs(4326, 3310, always_xy=True).transform
            positive = box(280, 280, 520, 520)
            self.assertTrue(any(transform(project, shape(f['geometry'])).difference(positive).area > 1000 for f in original))
            self.assertTrue(all(transform(project, shape(f['geometry'])).difference(positive).area < .001 for f in restricted))

    def test_positive_support_does_not_clear_existing_quality_holds(self):
        from tests.gis.test_seafloor_habitat_quality import HOLD
        with tempfile.TemporaryDirectory() as tmp, native_fixture(Path(tmp)) as (source, _, _):
            source['row']['habitat_quality_hold'] = deepcopy(HOLD)
            cells = [{'id': f'3310:{x}:{y}', 'tier': 1, 'source_id': 'original'} for x in range(4) for y in range(4)]
            result = habitat.build_candidates([source], cells, {}, RULES, {'id': 'fixture'}, root=tmp)
            self.assertTrue(result['features'])
            self.assertEqual(result['calibration_terrain_support'], {'original': support.binding_digest(source['row'])})
            for feature in result['features']:
                self.assertIn('source-habitat-quality-review', feature['properties']['hold_reasons'])
                self.assertIn('habitat-threshold-quality-review', feature['properties']['hold_reasons'])
                self.assertFalse(feature['properties']['exportable'])

    def test_publication_requires_current_direct_and_indirect_support_evidence(self):
        for case in ('current', 'missing-inventory', 'missing-feature', 'changed-binding',
                     'removed-binding', 'zero-own-contributor', 'unused-binding'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with native_fixture(root) as (source, _, _):
                    direct = deepcopy(source['row']); indirect = deepcopy(direct)
                    indirect['id'] = 'indirect'; indirect['terrain_support']['depth_source_id'] = 'indirect'
                    if case in ('zero-own-contributor', 'unused-binding'):
                        direct.pop('terrain_support')
                    old = [deepcopy(direct), deepcopy(indirect)]
                    calibration = ['original'] if case == 'unused-binding' else ['original', 'indirect']
                    candidates = {'calibration_source_ids': calibration}
                    expected = {r['id']: support.binding_digest(r) for r in old
                                if r['id'] in calibration and r.get('terrain_support')}
                    if expected: candidates['calibration_terrain_support'] = expected
                    props = {'tier': 2, 'status': 'habitat', 'exportable': True, 'screen': {'status': 'pass'},
                             'source_ids': ['original'], 'hold_reasons': [],
                             'terrain': {'grade': 'A', 'score': 8}, 'fit': {'lingcod': 3}}
                    if direct.get('terrain_support'): props['terrain_support'] = support.feature_evidence(direct)
                    if case in ('missing-inventory', 'zero-own-contributor'):
                        candidates.pop('calibration_terrain_support')
                    if case == 'missing-feature': props.pop('terrain_support')
                    if case == 'changed-binding': indirect['terrain_support']['metadata_sha256'] = 'e'*64
                    if case == 'removed-binding': direct.pop('terrain_support')
                    atomic_json(root/'catalog/surveys.json', {'surveys': [direct, indirect]})
                    ref = root/'var/seafloor/reference/cells.json'; atomic_json(ref, {'cells': []})
                    atomic_json(root/'dist/data/seafloor-ledger.json', {'reference_cells_sha256': sha256(ref),
                        'reaches': [{'id': 'r01', 'region': 'fixture', 'status': 'partial'}]})
                    folder = root/'var/seafloor/reaches/r01'
                    atomic_json(folder/'candidates.geojson', candidates)
                    atomic_json(folder/'habitat.geojson', {'features': [{'properties': props,
                        'geometry': {'type': 'Point', 'coordinates': [-120, 35]}}]})
                    atomic_json(folder/'cells.json', {'cells': []})
                    atomic_json(folder/'run.json', {'input_hash': 'fixture', 'ledger_summary': {},
                        'inputs': {'screen': 'now', 'sources': old},
                        'outputs': {name: sha256(folder/name) for name in ('candidates.geojson', 'habitat.geojson', 'cells.json')}})
                    with patch.object(publish, 'load_snapshot', return_value={'status': 'ready',
                            'snapshot': '2026-01-01T00:00:00Z', 'layers': []}), \
                            patch.object(publish, 'input_identity', return_value='now'), \
                            patch.object(publish, 'feature_rights', return_value=[]), \
                            patch.object(publish, 'deployment_use', return_value='noncommercial'):
                        if case in ('current', 'unused-binding'):
                            layers, _, _ = publish.region_layers(root, 'fixture', rerun=False)
                            self.assertEqual(len(layers['habitat']), 1)
                        else:
                            with self.assertRaisesRegex(ValueError, 'support'):
                                publish.region_layers(root, 'fixture', rerun=False)

    def test_exact_legend_preserves_zero_smooth_and_nodata_unknown(self):
        values = np.array([[-1, -31, -101, -201, 0, -30, -100, -200, -32768]])
        actual = support.classify(values, values != -32768)
        np.testing.assert_array_equal(actual, [[True]*4+[False]*5])
        for bad in (2, np.nan, -.5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                support.classify(np.array([[bad]]), np.ones((1, 1), bool))

    def test_native_alignment_metadata_and_depth_hash_fail_closed(self):
        for case in ('alignment', 'metadata', 'normalized-depth', 'depth-id', 'depth-member', 'source-hash', 'legend', 'traversal'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                with native_fixture(Path(tmp), offset=.5 if case == 'alignment' else 0,
                        metadata_hash='b'*64 if case == 'metadata' else None) as (source, grid, codes):
                    binding = source['row']['terrain_support']
                    field_value = {'normalized-depth': ('depth_cog_sha256', 'c'*64),
                        'depth-id': ('depth_source_id', 'sibling'), 'depth-member': ('depth_archive_member', 'sibling.zip/depth'),
                        'source-hash': ('source_sha256', 'd'*64), 'legend': ('rough_codes', [-1, 0]),
                        'traversal': ('archive_member', '../escape')}.get(case)
                    if field_value: binding[field_value[0]] = field_value[1]
                    with self.assertRaises(ValueError):
                        support.read_support(source, grid['depth'].shape, grid['affine'], root=tmp)

    def test_positive_support_changes_calibration_not_depth_or_substrate(self):
        codes = np.full((400, 400), 0, 'int16'); codes[130:270, 130:270] = -1
        codes[160:163, :] = -32768
        with tempfile.TemporaryDirectory() as tmp, native_fixture(Path(tmp), codes=codes) as (source, original, _):
            cells = [{'id': f'3310:{x}:{y}', 'tier': 1, 'source_id': 'original'} for x in range(4) for y in range(4)]
            actual = habitat.source_grid(source, cells, None, root=tmp)
            self.assertTrue(np.all(actual['classes'] == 0))
            self.assertEqual(np.count_nonzero(actual['valid']), 160000)
            np.testing.assert_array_equal(actual['depth'], original['depth'])
            np.testing.assert_array_equal(actual['inside'], codes == -1)
            limits = habitat.thresholds([actual], RULES)
            self.assertEqual(limits['vrm_samples'], np.count_nonzero((codes == -1) & np.isfinite(actual['terrain']['vrm'])))
            features = habitat.extract_grid(actual, limits, RULES, {'id': 'fixture'})
            self.assertTrue(features)
            for feature in features:
                evidence = feature['properties']['terrain_support']
                self.assertEqual(evidence['binding_sha256'], support.binding_digest(source['row']))
                self.assertFalse(evidence['independent_confirmation'])
                self.assertEqual(feature['properties']['substrate']['source_id'], 'unknown')

    def test_tiled_reader_and_extraction_match_with_mask_holes_and_edges(self):
        codes = np.full((400, 400), -1, 'int16')
        codes[:, 127:130] = 0; codes[255:258, :] = -32768
        with tempfile.TemporaryDirectory() as tmp, native_fixture(Path(tmp), codes=codes) as (source, grid, _):
            cells = [{'id': f'3310:{x}:{y}', 'tier': 1, 'source_id': 'original'} for x in range(4) for y in range(4)]
            monolithic = habitat.source_grid(source, cells, None, root=tmp)
            for edge in (73, 128):
                with self.subTest(edge=edge), tiled.scratch(Path(tmp)/'scratch') as disk:
                    with rasterio.open(source['path']) as original, WarpedVRT(original, crs=3310,
                            transform=grid['affine'], width=400, height=400, nodata=np.nan) as vrt:
                        streamed = tiled.source_grid(vrt, Window(0, 0, 400, 400), source,
                            grid['support'], None, root=tmp, scratch=disk, edge=edge)
                    np.testing.assert_array_equal(streamed['inside'], monolithic['inside'])
                    np.testing.assert_array_equal(streamed['depth'], monolithic['depth'])
                    limits = habitat.thresholds([monolithic], RULES)
                    tiled_limits = tiled.thresholds([streamed], RULES, disk, edge)
                    # Derivative reduction order has machine-epsilon differences
                    # on flat cells, far below the unchanged VRM-zero rule.
                    self.assertAlmostEqual(limits['vrm'], tiled_limits['vrm'], places=12)
                    self.assertAlmostEqual(limits['bpi_fine_m'], tiled_limits['bpi_fine_m'], places=12)
                    expected = habitat.extract_grid(monolithic, limits, RULES, {'id': 'fixture'})
                    actual = tiled.extract_grid(streamed, tiled_limits, RULES, {'id': 'fixture'}, disk, edge)
                    self.assertEqual(sorted(actual, key=lambda f: f['properties']['id']),
                                     sorted(expected, key=lambda f: f['properties']['id']))

    def test_morphology_cannot_bridge_support_or_depth_holes(self):
        grid = fixture(); grid['terrain']['vrm'][:] = .2
        grid['inside'][:, 127] = False
        grid['depth'][255, :] = 91.45
        grid['depth'][256, :] = np.nan; grid['valid'][256, :] = False
        rough = habitat.rough_mask(grid['depth'], grid['valid'], grid['inside'], grid['terrain'],
            grid['classes'], {'vrm': .1, 'bpi_fine_m': 100}, RULES)
        self.assertFalse(rough[:, 127].any()); self.assertFalse(rough[255:257, :].any())

    def test_empty_support_has_no_calibration_or_candidates(self):
        grid = fixture(); grid['inside'][:] = False
        limits = habitat.thresholds([grid], RULES)
        self.assertEqual(limits['vrm'], 'unknown'); self.assertEqual(limits['vrm_samples'], 0)
        self.assertEqual(habitat.extract_grid(grid, limits, RULES, {'id': 'fixture'}), [])
        with tempfile.TemporaryDirectory() as tmp, tiled.scratch(tmp) as disk:
            self.assertEqual(tiled.thresholds([grid], RULES, disk, 73), limits)
            self.assertEqual(tiled.extract_grid(grid, limits, RULES, {'id': 'fixture'}, disk, 73), [])

    def test_absent_binding_is_identity_and_shared_calibration_changes_are_explicit(self):
        grid = fixture(); before = deepcopy(grid)
        with tempfile.TemporaryDirectory() as tmp:
            identity = support.read_support(grid['source'], grid['depth'].shape, grid['affine'], root=tmp)
        grid['inside'] &= identity
        self.assertEqual(habitat.thresholds([grid], RULES), habitat.thresholds([before], RULES))
        self.assertEqual(habitat.extract_grid(grid, habitat.thresholds([grid], RULES), RULES, {'id': 'fixture'}),
                         habitat.extract_grid(before, habitat.thresholds([before], RULES), RULES, {'id': 'fixture'}))
        other = fixture(); other['terrain']['vrm'] *= 100
        original = habitat.thresholds([grid, other], RULES)
        other['inside'][:] = False
        restricted = habitat.thresholds([grid, other], RULES)
        self.assertNotEqual(original['vrm'], restricted['vrm'])
        self.assertEqual(restricted, habitat.thresholds([grid], RULES))

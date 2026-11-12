"""Tiled processing must match native small-grid science and cross seams."""
from copy import deepcopy
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

from skippercast.seafloor import habitat, habitat_tiles as tiled
from tests.gis.test_seafloor_habitat import fixture, RULES


class TiledHabitatTests(unittest.TestCase):
    def test_global_thresholds_are_identical_across_tile_sizes_and_sources(self):
        a, b = fixture(), fixture()
        b['terrain']['vrm'] *= 4
        expected = habitat.thresholds([a, b], RULES)
        for edge in (37, 128):
            with self.subTest(edge=edge), tempfile.TemporaryDirectory() as directory, tiled.scratch(directory) as disk:
                actual = tiled.thresholds([a, b], RULES, disk, edge)
                self.assertEqual(actual['vrm_samples'], expected['vrm_samples'])
                self.assertEqual(actual['bpi_fine_m_samples'], expected['bpi_fine_m_samples'])
                self.assertEqual(actual['vrm'], expected['vrm'])
                self.assertAlmostEqual(actual['bpi_fine_m'], expected['bpi_fine_m'], places=12)

    def test_native_derivative_halos_match_whole_grid_at_tile_seams(self):
        grid = fixture()
        grid['depth'][180:186, 210:218] = np.nan
        grid['valid'] = np.isfinite(grid['depth'])
        grid['terrain'] = habitat.derivatives(grid['depth'], grid['valid'], 2)
        with tempfile.TemporaryDirectory() as directory, tiled.scratch(Path(directory)/'scratch') as disk:
            path = Path(directory)/'depth.tif'
            with rasterio.open(path, 'w', driver='GTiff', width=400, height=400, count=1,
                               dtype='float32', crs='EPSG:3310', transform=grid['affine'], nodata=np.nan) as target:
                target.write(grid['depth'], 1)
            source = {'path': path, 'row': grid['source']['row']}
            with rasterio.open(path) as original, WarpedVRT(original, crs='EPSG:3310',
                    transform=grid['affine'], width=400, height=400, nodata=np.nan) as vrt:
                actual = tiled.source_grid(vrt, Window(0, 0, 400, 400), source,
                                           grid['support'], None, root=Path(directory), scratch=disk, edge=128)
            np.testing.assert_array_equal(actual['valid'], grid['valid'])
            for key in ('vrm', 'bpi_fine_m'):
                np.testing.assert_allclose(actual['terrain'][key], grid['terrain'][key].astype('float32'),
                                           atol=1e-7, rtol=1e-6, equal_nan=True)
            self.assertLess(actual['processing']['max_read_pixels'], 400*400)

    def test_cross_tile_patch_geometry_metrics_and_ids_match_monolithic(self):
        grid = fixture(); limits = habitat.thresholds([grid], RULES)
        expected = habitat.extract_grid(grid, limits, RULES, {'id': 'fixture', 'region': 'fixture'})
        self.assertTrue(expected)
        for edge in (73, 128):
            with self.subTest(edge=edge), tempfile.TemporaryDirectory() as directory, tiled.scratch(directory) as disk:
                actual = tiled.extract_grid(grid, limits, RULES, {'id': 'fixture', 'region': 'fixture'}, disk, edge)
                self.assertEqual(sorted(actual, key=lambda f: f['properties']['id']),
                                 sorted(expected, key=lambda f: f['properties']['id']))

    def test_soft_nodata_and_depth_edges_do_not_bridge_at_a_tile_boundary(self):
        grid = fixture()
        grid['terrain']['vrm'][:] = .2
        grid['classes'][:, 127:130] = 1
        grid['valid'][255:258, :] = False
        grid['depth'][180:183, :] = 92
        limits = {'vrm': .1, 'bpi_fine_m': 100}
        expected = habitat.extract_grid(grid, limits, RULES, {'id': 'fixture', 'region': 'fixture'})
        with tempfile.TemporaryDirectory() as directory, tiled.scratch(directory) as disk:
            actual = tiled.extract_grid(grid, limits, RULES, {'id': 'fixture', 'region': 'fixture'}, disk, 128)
            self.assertEqual(sorted(actual, key=lambda f: f['properties']['id']),
                             sorted(expected, key=lambda f: f['properties']['id']))
            self.assertTrue(all(f['properties']['depth_max_ft'] <= 300 for f in actual))

    def test_diagonal_join_happens_before_minimum_area_filter(self):
        grid = fixture()
        grid['terrain']['vrm'][:] = 0
        grid['terrain']['bpi_fine_m'][:] = 0
        # Each 16x16 piece is below the 2000 m² test minimum; together they pass.
        grid['terrain']['vrm'][112:128, 112:128] = .2
        grid['terrain']['vrm'][128:144, 128:144] = .2
        rules = deepcopy(RULES); rules['minimum_patch_m2'] = 2000
        limits = {'vrm': .1, 'bpi_fine_m': 100}
        expected = habitat.extract_grid(grid, limits, rules, {'id': 'fixture', 'region': 'fixture'})
        self.assertEqual(len(expected), 1)
        with tempfile.TemporaryDirectory() as directory, tiled.scratch(directory) as disk:
            actual = tiled.extract_grid(grid, limits, rules, {'id': 'fixture', 'region': 'fixture'}, disk, 128)
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual[0]['properties'], expected[0]['properties'])
            # Equivalent rings may begin at a different vertex after streamed polygonization.
            self.assertTrue(shape(actual[0]['geometry']).equals(shape(expected[0]['geometry'])))

    def test_above_twenty_million_native_pixels_completes_with_bounded_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/'large.tif'
            width, height = 5000, 4200
            affine = from_origin(0, 8400, 2, 2)
            with rasterio.open(path, 'w', driver='GTiff', width=width, height=height, count=1,
                               dtype='float32', crs='EPSG:3310', transform=affine,
                               tiled=True, compress='lzw', nodata=np.nan) as target:
                for core, _, _ in tiled.windows((height, width)):
                    ys, xs = core
                    target.write(np.full((ys.stop-ys.start, xs.stop-xs.start), 50, 'float32'), 1,
                                 window=Window(xs.start, ys.start, xs.stop-xs.start, ys.stop-ys.start))
            source = {'path': path, 'geometry': box(0, 0, 10000, 8400),
                      'row': {'id': 'large-native', 'resolution_m': 2, 'year': 2008, 'vertical_datum': 'unknown'}}
            cells = [{'id': '3310:0:0', 'tier': 1, 'source_id': 'large-native'},
                     {'id': '3310:39:33', 'tier': 1, 'source_id': 'large-native'}]
            result = habitat.build_candidates([source], cells, {}, RULES, {'id': 'large', 'region': 'fixture'}, root=root)
            method = result['processing'][0]
            self.assertGreater(method['window_pixels'], 20_000_000)
            self.assertLess(method['max_read_pixels'], 1_300_000)
            self.assertEqual(method['method'], 'native-disk-backed-tiles-v1')
            self.assertEqual(result['features'], [])  # genuinely flat measured bottom
            self.assertEqual(list((root/'var/seafloor/scratch').iterdir()), [])

    def test_scratch_arrays_close_after_interrupted_processing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                with tiled.scratch(directory) as disk:
                    value = disk.array((100, 100), 'float32')
                    raise RuntimeError('interrupted')
            self.assertTrue(value._mmap.closed)

    def test_scratch_cleanup_on_failure_and_no_silent_disk_fallback(self):
        with tempfile.TemporaryDirectory() as directory, tiled.scratch(directory) as disk:
            with patch.object(tiled.shutil, 'disk_usage', return_value=type('Space', (), {'free': 1})()):
                with self.assertRaisesRegex(ValueError, 'scratch disk'):
                    disk.array((100, 100), 'float32')


if __name__ == '__main__':
    unittest.main()

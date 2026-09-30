"""Offline reference geometry fixtures; no live source is needed for CI."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from shapely.geometry import LineString

from skippercast.seafloor.grid import (assign_reaches, cell_counts, classify_reference,
                                      make_reaches, merge_reference)
from skippercast.seafloor.reference import tile_sample
from tests._support import ROOT


class ReferenceGridTests(unittest.TestCase):
    def test_boundary_cells_have_one_owner_and_endpoints_are_excluded(self):
        spine = LineString([(0, 0), (1000, 0)])
        reaches = [{'end_m': 500}, {'end_m': 1000}]
        x = np.array([-125, 125, 375, 500, 625, 875, 1125])
        owners = assign_reaches(spine, reaches, x, np.full(x.shape, 125))
        np.testing.assert_array_equal(owners, [-1, 0, 0, 1, 1, 1, -1])
        left = set(np.flatnonzero(owners == 0))
        right = set(np.flatnonzero(owners == 1))
        self.assertFalse(left & right)
        self.assertEqual(len(left | right), 5)

    def test_nodata_and_land_are_not_shallow_water(self):
        elevations = np.array([[np.nan, 5, 0, -.1, -100, -100.1]])
        np.testing.assert_array_equal(classify_reference(elevations), [[0, 1, 1, 2, 2, 1]])

    def test_fine_valid_overwrites_coarse_and_holes_remain_unknown(self):
        coarse = np.array([[2, 2, 0], [1, 0, 0]], dtype='uint8')
        fine = np.array([[1, 0, 2], [2, 0, 0]], dtype='uint8')
        merge_reference(coarse, fine)
        np.testing.assert_array_equal(coarse, [[1, 2, 2], [2, 0, 0]])

    def test_band_area_is_fractional_and_overlap_is_not_added(self):
        mosaic = np.ones((10, 20), dtype='uint8')
        mosaic[:5, :10] = 2
        mosaic[5:, :10] = 0
        mosaic[:, 10:] = 2
        bands, unknown = cell_counts(mosaic, 10)
        np.testing.assert_array_equal(bands, [[50, 100]])
        np.testing.assert_array_equal(unknown, [[50, 0]])
        self.assertEqual(int(bands.sum()) * 625, 93750)
        before = bands.copy()
        merge_reference(mosaic, mosaic.copy())
        np.testing.assert_array_equal(cell_counts(mosaic, 10)[0], before)
        with self.assertRaises(ValueError):
            cell_counts(np.zeros((11, 10)), 10)

    def test_committed_spine_regenerates_exact_reach_geometry(self):
        config = json.loads((ROOT / 'catalog/seafloor-scope.json').read_text())
        catalog = json.loads((ROOT / 'catalog/reaches.json').read_text())
        spine = LineString(catalog['planning_spine_3310']['coordinates'])
        computed = make_reaches(config, spine)
        for actual, expected in zip(sorted(computed, key=lambda r: r['order']), catalog['reaches']):
            self.assertEqual((actual['id'], actual['region'], actual['order']),
                             (expected['id'], expected['region'], expected['order']))
            for key in ('start_m', 'end_m', 'length_m'):
                self.assertAlmostEqual(actual[key], expected[key], places=6)
            np.testing.assert_allclose(actual['geometry']['coordinates'],
                                       expected['geometry']['coordinates'], rtol=0, atol=1e-9)
        starts = sorted(catalog['reaches'], key=lambda r: r['start_m'])
        self.assertEqual(starts[0]['start_m'], 0)
        for a, b in zip(starts, starts[1:]):
            self.assertAlmostEqual(a['end_m'], b['start_m'], places=8)
        for reach in starts:
            self.assertGreater(reach['length_m'], 5000)
            self.assertLess(reach['length_m'], 15000)

    def test_sample_requires_explicit_network_opt_in(self):
        tile = {'id': 'fixture', 'url': 'https://example.invalid/a.tiff'}
        with tempfile.TemporaryDirectory() as temporary:
            with patch('skippercast.seafloor.reference.rasterio.open') as opening:
                with self.assertRaises(FileNotFoundError):
                    tile_sample(tile, Path(temporary), 32, fetch=False)
                with self.assertRaises(ValueError):
                    tile_sample(tile, Path(temporary), 32, fetch=True)
                opening.assert_not_called()

    @unittest.skipUnless((ROOT / 'var/seafloor/reference/cells.json').exists(),
                         'Private reference grid absent; committed ledger tested separately')
    def test_cached_grid_has_disjoint_ownership_and_reproduces_ledger(self):
        cells = json.loads((ROOT / 'var/seafloor/reference/cells.json').read_text())['cells']
        ledger = json.loads((ROOT / 'dist/data/seafloor-ledger.json').read_text())
        self.assertEqual(len(cells), len({c['id'] for c in cells}))
        by_reach = {r['id']: 0 for r in ledger['reaches']}
        for cell in cells:
            by_reach[cell['reach']] += cell['band_area_m2']
            self.assertEqual(cell['tier'], 0)
            self.assertLessEqual(cell['band_area_m2'] + cell['reference_unknown_area_m2'], 62500)
        for reach in ledger['reaches']:
            self.assertAlmostEqual(by_reach[reach['id']] / 1e6, reach['band_km2'], places=9)


if __name__ == '__main__':
    unittest.main()

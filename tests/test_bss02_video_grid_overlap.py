"""Camera observations cannot qualify unpopulated bathymetry cells."""
import json
from pathlib import Path
import unittest

import numpy as np
from rasterio.transform import from_origin

from research.scripts.audit_bss02_video_grid_overlap import near_valid_pixel, inspect


ROOT = Path(__file__).resolve().parents[1]


class Grid:
    transform = from_origin(0, 20, 2, 2)
    res = (2, 2)
    width = 10
    height = 10

    def index(self, x, y):
        return (int((20 - y) // 2), int(x // 2))


class VideoGridOverlapTest(unittest.TestCase):
    def test_metric_radius_does_not_use_rectangular_bounds_as_coverage(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[5, 5] = True
        self.assertTrue(near_valid_pixel(mask, Grid(), 11, 9, 1))
        self.assertFalse(near_valid_pixel(mask, Grid(), 1, 19, 1))
        self.assertTrue(near_valid_pixel(mask, Grid(), 1, 19, 15))

    def test_original_receipt_has_no_camera_grid_join(self):
        receipt = json.loads((ROOT / 'dist/data/bss02-video-grid-overlap.json').read_text())
        self.assertEqual(receipt['camera_records_inside_raster_bounds'], 46)
        self.assertEqual(receipt['interpreted_bottom_windows'], 39)
        self.assertEqual(receipt['rock_boulder_cobble_windows'], 11)
        self.assertEqual(receipt['camera_records_on_valid_depth_pixel'], 0)
        self.assertEqual(receipt['camera_records_within_100m_of_valid_depth_pixel'], 0)
        self.assertFalse(receipt['independent_observations_on_populated_grid'])
        self.assertFalse(receipt['fishing_target'])
        self.assertFalse(receipt['exportable'])

    def test_adjacent_block_has_real_but_limited_source_datum_overlap(self):
        receipt = json.loads((ROOT / 'dist/data/bss03-video-grid-overlap.json').read_text())
        self.assertEqual(receipt['camera_records_on_valid_depth_pixel'], 46)
        self.assertEqual(receipt['camera_windows_in_200_300ft_source_datum_band'], 46)
        self.assertEqual(receipt['rock_boulder_cobble_windows_in_band'], 11)
        self.assertEqual(receipt['rock_boulder_cobble_windows_on_derived_rough_class'], 3)
        self.assertEqual(receipt['rock_boulder_cobble_windows_within_10m_of_derived_rough_class'], 10)
        self.assertEqual(receipt['rock_boulder_cobble_windows_within_25m_of_derived_rough_class'], 11)
        self.assertEqual(receipt['distinct_nonempty_camera_line_ids_in_band'], 1)
        self.assertGreater(receipt['source_depth_range_m_on_populated_band'][0], -91.44)
        self.assertLess(receipt['source_depth_range_m_on_populated_band'][1], -60.96)
        self.assertTrue(receipt['independent_observations_on_populated_grid'])
        self.assertEqual(receipt['rank_effect'], 'none')
        self.assertFalse(receipt['fishing_target'])

    def test_hash_pinned_sources_reproduce_receipt_when_cached(self):
        bss_cache = ROOT / 'var/review/csumb-bss-cache'
        video_cache = ROOT / 'var/usgs-video-cache'
        if not ((bss_cache / 'BSS_Block02_additional_products.tar.gz').exists()
                and (video_cache / 'c0212sc_video_observations.zip').exists()):
            self.skipTest('Original archives not cached locally')
        bss = next(source for source in json.loads((ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
                   if source['survey_id'] == 'BSS_Block02')
        video = json.loads((ROOT / 'catalog/usgs-video-cruises.json').read_text())
        actual = inspect(bss, video, bss_cache, video_cache)
        expected = json.loads((ROOT / 'dist/data/bss02-video-grid-overlap.json').read_text())
        self.assertEqual(actual, expected)

    def test_adjacent_block_reproduces_when_cached(self):
        bss_cache = ROOT / 'var/review/csumb-bss-cache'
        video_cache = ROOT / 'var/usgs-video-cache'
        if not ((bss_cache / 'BSS_Block03_additional_products.tar.gz').exists()
                and (video_cache / 'c0212sc_video_observations.zip').exists()):
            self.skipTest('Original archives not cached locally')
        bss = next(source for source in json.loads((ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
                   if source['survey_id'] == 'BSS_Block03')
        video = json.loads((ROOT / 'catalog/usgs-video-cruises.json').read_text())
        actual = inspect(bss, video, bss_cache, video_cache)
        expected = json.loads((ROOT / 'dist/data/bss03-video-grid-overlap.json').read_text())
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()

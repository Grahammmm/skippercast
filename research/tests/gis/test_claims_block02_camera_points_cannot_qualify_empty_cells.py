"""Camera observations cannot qualify unpopulated bathymetry cells."""
import json
import unittest

import numpy as np
from rasterio.transform import from_origin

from research.scripts.audit_bss02_video_grid_overlap import (
    OFF_KEY, UNKNOWN_KEY, inspect, legacy_view, near_valid_pixel, receipt_matches_baseline)
from research.lib.receipts import RECEIPTS
from research.lib.paths import ROOT


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
        receipt = json.loads((RECEIPTS / 'bss02-video-grid-overlap.json').read_text())
        self.assertEqual(receipt['camera_records_inside_raster_bounds'], 46)
        self.assertEqual(receipt['interpreted_bottom_windows'], 39)
        self.assertEqual(receipt['rock_boulder_cobble_windows'], 11)
        self.assertEqual(receipt['camera_records_on_valid_depth_pixel'], 0)
        self.assertEqual(receipt['camera_records_within_100m_of_valid_depth_pixel'], 0)
        self.assertFalse(receipt['independent_observations_on_populated_grid'])
        self.assertFalse(receipt['fishing_target'])
        self.assertFalse(receipt['exportable'])

    def test_adjacent_block_has_real_but_limited_source_datum_overlap(self):
        receipt = json.loads((RECEIPTS / 'bss03-video-grid-overlap.json').read_text())
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
        video = json.loads((ROOT / 'research/catalog/usgs-video-cruises.json').read_text())
        actual = inspect(bss, video, bss_cache, video_cache)
        expected = json.loads((RECEIPTS / 'bss02-video-grid-overlap.json').read_text())
        self.assertEqual(legacy_view(actual), expected)

    def test_adjacent_block_reproduces_when_cached(self):
        bss_cache = ROOT / 'var/review/csumb-bss-cache'
        video_cache = ROOT / 'var/usgs-video-cache'
        if not ((bss_cache / 'BSS_Block03_additional_products.tar.gz').exists()
                and (video_cache / 'c0212sc_video_observations.zip').exists()):
            self.skipTest('Original archives not cached locally')
        bss = next(source for source in json.loads((ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
                   if source['survey_id'] == 'BSS_Block03')
        video = json.loads((ROOT / 'research/catalog/usgs-video-cruises.json').read_text())
        actual = inspect(bss, video, bss_cache, video_cache)
        expected = json.loads((RECEIPTS / 'bss03-video-grid-overlap.json').read_text())
        self.assertEqual(legacy_view(actual), expected)

    # Contract: --verify against a reviewed receipt written before the unknown
    # class existed still works, and still fails on any changed aggregate.
    # Bug caught: comparing the split receipt to a legacy one with plain
    # equality always fails on the new key, or a loose fold hides a real change.
    def test_legacy_baseline_verifies_split_receipt_without_rewriting_it(self):
        baseline = json.loads((RECEIPTS / 'bss03-video-grid-overlap.json').read_text())
        self.assertNotIn(UNKNOWN_KEY, baseline)
        off = baseline[OFF_KEY]
        for unknown in (0, 3, off):
            split = {**baseline, OFF_KEY: off - unknown, UNKNOWN_KEY: unknown}
            self.assertTrue(receipt_matches_baseline(split, baseline))
        self.assertEqual(baseline[OFF_KEY], 8)  # the reviewed aggregate is untouched

    def test_legacy_baseline_still_rejects_changed_aggregates(self):
        baseline = json.loads((RECEIPTS / 'bss03-video-grid-overlap.json').read_text())
        split = {**baseline, OFF_KEY: 5, UNKNOWN_KEY: 3}
        for key, value in (
                (OFF_KEY, 6),  # off + unknown no longer equals the reviewed total
                (UNKNOWN_KEY, 2),
                ('rock_boulder_cobble_windows_on_derived_rough_class', 4),
                ('camera_records_within_100m_of_valid_depth_pixel', 64)):
            with self.subTest(key=key):
                self.assertFalse(receipt_matches_baseline({**split, key: value}, baseline))

    def test_baseline_with_unknown_key_is_compared_exactly(self):
        baseline = {'a': 1, OFF_KEY: 5, UNKNOWN_KEY: 3}
        self.assertTrue(receipt_matches_baseline(dict(baseline), baseline))
        self.assertFalse(receipt_matches_baseline({**baseline, OFF_KEY: 6, UNKNOWN_KEY: 2}, baseline))


if __name__ == '__main__':
    unittest.main()

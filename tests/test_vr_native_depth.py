import unittest

import numpy as np

from scripts.screen_vr_native_depth import native_counts, containing_sector, summarize_by_sector


class VariableResolutionNativeReviewTest(unittest.TestCase):
    def test_anisotropic_native_grid_uses_both_original_cell_dimensions(self):
        metadata = np.array((0, 2, 2, 2.0128, 2.0334, 1, 1), dtype=[
            ('index', 'u4'), ('dimensions_x', 'u4'), ('dimensions_y', 'u4'),
            ('resolution_x', 'f4'), ('resolution_y', 'f4'),
            ('sw_corner_x', 'f4'), ('sw_corner_y', 'f4')])
        cells = np.array([[(-30, .2), (-65, .2), (1e6, 1e6), (-29, .2)]],
                         dtype=[('depth', 'f4'), ('depth_uncrt', 'f4')])
        self.assertEqual(native_counts(cells, metadata), (3, 2))

    def test_bad_index_fails_before_reading_refinements(self):
        metadata = np.array((3, 2, 2, 2, 2, 1, 1), dtype=[
            ('index', 'u4'), ('dimensions_x', 'u4'), ('dimensions_y', 'u4'),
            ('resolution_x', 'f4'), ('resolution_y', 'f4'),
            ('sw_corner_x', 'f4'), ('sw_corner_y', 'f4')])
        cells = np.zeros((1, 4), dtype=[('depth', 'f4'), ('depth_uncrt', 'f4')])
        with self.assertRaisesRegex(ValueError, 'outside refinements'):
            native_counts(cells, metadata)

    def test_sector_assignment_requires_original_request_bounds(self):
        sectors = [{'id': 'a', 'bounds': [-124, 35, -123, 36]}]
        self.assertEqual(containing_sector(-123.5, 35.5, sectors), 'a')
        self.assertIsNone(containing_sector(-122, 35.5, sectors))

    def test_sector_summary_keeps_empty_sectors_and_review_only_counts(self):
        sectors = [{'id': 'a'}, {'id': 'b'}]
        files = [{'status': 'ok', 'sectors': {'a': {'fine_native_grids': 2,
                  'measured_native_cells': 8, 'depth_uncertainty_eligible_cells': 3}}},
                 {'status': 'ok', 'sectors': {'a': {'fine_native_grids': 1,
                  'measured_native_cells': 4, 'depth_uncertainty_eligible_cells': 0}}},
                 {'status': 'failed'}]
        summary = summarize_by_sector(files, sectors)
        self.assertEqual(summary[0]['source_files_with_fine_grids'], 2)
        self.assertEqual(summary[0]['source_files_with_eligible_cells'], 1)
        self.assertEqual(summary[0]['depth_uncertainty_eligible_cells'], 3)
        self.assertEqual(summary[1]['fine_native_grids'], 0)


if __name__ == '__main__':
    unittest.main()

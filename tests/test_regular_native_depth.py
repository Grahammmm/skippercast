import unittest

import numpy as np

from scripts.screen_regular_native_depth import (count_sector_cells, regular_audited_rows,
                                                  summarize_by_sector)


class RegularNativeDepthTests(unittest.TestCase):
    def test_assigns_native_cells_across_sector_boundary_without_double_count(self):
        sectors = [{'id': 'south', 'bounds': [-125, 34, -120, 35]},
                   {'id': 'north', 'bounds': [-125, 35, -120, 36]}]
        lon = np.array([[-121., -121., -119.]])
        lat = np.array([[34.999, 35., 35.]])
        measured = np.array([[True, True, True]])
        eligible = np.array([[True, False, True]])
        counts, outside = count_sector_cells(lon, lat, measured, eligible, sectors)
        self.assertEqual(outside, 1)
        self.assertEqual(counts['south'], {'measured_native_cells': 1,
                                          'depth_uncertainty_eligible_cells': 1})
        self.assertEqual(counts['north'], {'measured_native_cells': 1,
                                          'depth_uncertainty_eligible_cells': 0})

    def test_rejects_overlapping_envelopes(self):
        sectors = [{'id': 'one', 'bounds': [-125, 34, -120, 36]},
                   {'id': 'two', 'bounds': [-125, 35, -120, 37]}]
        one = np.array([[35.5]])
        with self.assertRaisesRegex(ValueError, 'overlap'):
            count_sector_cells(np.array([[-121.]]), one,
                               np.array([[True]]), np.array([[True]]), sectors)

    def test_selects_only_audited_regular_fine_grid(self):
        base = {'status': 'ok', 'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                'variable_refinement_records': 0, 'overview_resolution_m': [2, 2]}
        rows = [dict(base), dict(base, variable_refinement_records=100),
                dict(base, overview_resolution_m=[8, 8]), dict(base, status='failed')]
        self.assertEqual(regular_audited_rows({'files': rows}), [base])

    def test_sector_summary_does_not_count_failed_files(self):
        sectors = [{'id': 'north'}, {'id': 'south'}]
        source = {'status': 'ok', 'sectors': {'north': {'measured_native_cells': 20,
                   'depth_uncertainty_eligible_cells': 4}}}
        failed = {'status': 'failed', 'sectors': source['sectors']}
        summary = summarize_by_sector([source, failed], sectors)
        self.assertEqual(summary[0]['source_files_with_eligible_cells'], 1)
        self.assertEqual(summary[0]['measured_native_cells'], 20)
        self.assertEqual(summary[1]['measured_native_cells'], 0)


if __name__ == '__main__':
    unittest.main()

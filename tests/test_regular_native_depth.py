import unittest

import numpy as np

from scripts.screen_regular_native_depth import (count_sector_cells, regular_audited_rows,
                                                  summarize_by_sector)
from scripts.inspect_noaa_bag_grids import scan


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

    def test_offshore_island_cells_are_not_mislabeled_as_mainland(self):
        sectors = [{'id': 'los-angeles-orange', 'bounds': [-121.25, 33.45, -116.95, 33.75]}]
        islands = [{'id': 'santa-barbara-island', 'bounds': [-119.13, 33.41, -118.95, 33.55]}]
        counts = {}
        mainland, outside = count_sector_cells(np.array([[-119.05, -118.10]]),
            np.array([[33.50, 33.50]]), np.array([[True, True]]),
            np.array([[True, False]]), sectors, islands, counts)
        self.assertEqual(outside, 0)
        self.assertEqual(mainland['los-angeles-orange']['measured_native_cells'], 1)
        self.assertEqual(counts['santa-barbara-island'], {
            'measured_native_cells': 1, 'depth_uncertainty_eligible_cells': 1})

    def test_selects_only_audited_regular_fine_grid(self):
        base = {'status': 'ok', 'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                'variable_refinement_records': 0, 'overview_resolution_m': [2, 2]}
        rows = [dict(base), dict(base, variable_refinement_records=100),
                dict(base, overview_resolution_m=[8, 8]), dict(base, status='failed')]
        self.assertEqual(regular_audited_rows({'files': rows}), [base])

    def test_large_survey_selection_fails_if_requested_source_is_missing(self):
        inventory = {'scope': 'noaa-bag-head-inventory', 'files': []}
        products = {'scope': 'noaa-survey-product-links', 'surveys': []}
        with self.assertRaisesRegex(ValueError, 'Requested survey'):
            scan(inventory, products, None, max_bytes=200_000_000,
                 survey_ids=['W00456'])

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

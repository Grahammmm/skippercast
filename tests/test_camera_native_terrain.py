"""The original-cell terrain receipt must stay measurable and non-promotional."""
import json
import unittest
from pathlib import Path

import numpy as np

from scripts.audit_camera_native_terrain import fit_terrain


ROOT = Path(__file__).resolve().parents[1]


class CameraNativeTerrainTests(unittest.TestCase):
    def test_plane_detrending_separates_slope_from_local_relief(self):
        offsets = np.arange(-14, 15) * 2.0
        dx, dy = np.meshgrid(offsets, offsets)
        within = dx * dx + dy * dy <= 25 * 25
        plane = -40 + .05 * dx + .02 * dy
        uncertainty = np.full(plane.shape, .3)
        flat = fit_terrain(plane, uncertainty, dx, dy, within, resolution_m=2)
        bump = plane + 1.2 * np.exp(-(dx * dx + dy * dy) / (2 * 8 * 8))
        rough = fit_terrain(bump, uncertainty, dx, dy, within, resolution_m=2)
        self.assertLess(flat['detrended_p95_p05_relief_m'], .001)
        self.assertGreater(rough['detrended_p95_p05_relief_m'], .3)
        self.assertGreater(flat['fitted_plane_slope_degrees'], 2)
        incomplete = uncertainty.copy()
        incomplete[:, :14] = 2
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            fit_terrain(plane, incomplete, dx, dy, within, resolution_m=2)

    def test_bear_landing_receipt_does_not_turn_transects_into_targets(self):
        report = json.loads((ROOT / 'dist/data/h11971-bear-landing-native-terrain.json').read_text())
        self.assertEqual([row['historical_camera_windows'] for row in report['transects']], [5, 8])
        self.assertFalse(report['fishing_target'])
        self.assertFalse(report['exportable'])
        self.assertNotIn('camera_position_bounds', json.dumps(report))
        cobble, rock = report['transects']
        self.assertGreater(rock['detrended_p95_p05_relief_m_range'][0],
                           cobble['detrended_p95_p05_relief_m_range'][1])

    def test_second_coast_reuses_method_without_a_global_rock_threshold(self):
        north = json.loads((ROOT / 'dist/data/h11971-bear-landing-native-terrain.json').read_text())
        south = json.loads((ROOT / 'dist/data/h11876-la-jolla-native-terrain.json').read_text())
        self.assertEqual(north['method'], south['method'])
        self.assertEqual(south['survey_id'], 'H11876')
        self.assertEqual(sum(row['historical_camera_windows'] for row in south['transects']), 11)
        self.assertFalse(south['fishing_target'])
        self.assertNotIn('camera_position_bounds', json.dumps(south))
        self.assertLess(south['transects'][0]['detrended_p95_p05_relief_m_range'][0],
                        north['transects'][0]['detrended_p95_p05_relief_m_range'][1])

    def test_h11730_unheld_report_review_stays_research_only(self):
        pairs = json.loads((ROOT / 'dist/data/noaa-statewide-regular-camera-review.json').read_text())['pair_reviews']
        for cruise, suffix, count in (
            ('f208nc', '2008', 40), ('c210nc', '2010', 14)):
            report = json.loads((ROOT / f'dist/data/h11730-arena-bodega-{suffix}-native-terrain.json').read_text())
            pair = next(row for row in pairs if row['survey_id'] == 'H11730'
                        and row['cruise'] == cruise and row['bag_url'] == report['bag_url'])
            self.assertTrue(pair['report_hazard_review_complete'])
            self.assertIsNone(pair['survey_hold'])
            self.assertEqual(report['camera_archive_sha256'], pair['camera_archive_sha256'])
            self.assertEqual(sum(row['historical_camera_windows'] for row in report['transects']), count)
            self.assertFalse(report['fishing_target'])
            self.assertFalse(report['exportable'])
            self.assertNotIn('camera_position_bounds', json.dumps(report))


if __name__ == '__main__':
    unittest.main()

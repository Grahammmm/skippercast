import copy
import unittest

from scripts.build_monterey_300_research_queue import build


class MontereyBandQueueTests(unittest.TestCase):
    def setUp(self):
        self.audit = {
            "scope": "original-usgs-bathymetry-vs-habitat-context",
            "vertical_datum": "NAVD88", "mllw_conversion_reviewed": False,
            "product_uncertainty_grid_available": False, "fishing_target": False,
            "bathymetry_sha256": "abc", "context_outlines": 2,
            "outlines": [
                {"context_id": "a", "native_measured_cells": 100,
                 "historical_camera_interior_windows": 1,
                 "historical_rock_boulder_windows": 1,
                 "historical_rockfish_positive_windows": 0,
                 "depth_m_below_navd88": {"minimum": 50, "maximum": 70}},
                {"context_id": "b", "native_measured_cells": 500,
                 "historical_camera_interior_windows": 0,
                 "historical_rock_boulder_windows": 0,
                 "historical_rockfish_positive_windows": 0,
                 "depth_m_below_navd88": {"minimum": 20, "maximum": 40}},
            ],
        }

    def test_research_priority_does_not_infer_depth_or_fish(self):
        result = build(self.audit)
        self.assertEqual(result["possible_band_overlap_outline_count"], 1)
        self.assertEqual(result["priority_order"][0]["context_id"], "a")
        self.assertIsNone(result["priority_order"][0]["native_measured_cells_in_200_300ft_band"])
        self.assertFalse(result["exportable"])

    def test_rejects_promoted_or_converted_source(self):
        for key in ("fishing_target", "mllw_conversion_reviewed", "product_uncertainty_grid_available"):
            changed = copy.deepcopy(self.audit)
            changed[key] = True
            with self.assertRaises(ValueError):
                build(changed)


if __name__ == "__main__":
    unittest.main()

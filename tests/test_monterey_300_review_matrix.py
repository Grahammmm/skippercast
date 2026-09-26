import copy
import unittest

from scripts.build_monterey_300_review_matrix import build


class MontereyMatrixTests(unittest.TestCase):
    def test_joins_same_original_outline_without_promotion(self):
        row = {"context_id": "a", "native_navd88_band_cells": 10,
               "paired_original_class3_hard_band_cells": 8,
               "historical_camera_windows": 1, "historical_rockfish_positive_windows": 1}
        paired = {"scope": "monterey-original-paired-hard-depth-band-audit", "fishing_target": False,
                  "outline_count": 1, "audited_at": "now", "outlines": [row]}
        closure = {"scope": "monterey-original-300-research-closure-screen", "fishing_target": False,
                   "audited_at": "now", "outlines": [{"context_id": "a", "native_200_300ft_navd88_cells": 10,
                       "within_100m_closure_review_buffer": False, "nearest_cdfw_mpa_m": 300,
                       "nearest_noaa_gea_m": 1000}]}
        enc = {"scope": "monterey-original-300-enc-danger-screen", "fishing_target": False,
               "audited_at": "now", "outlines": [{"context_id": "a",
                   "within_charted_danger_review_buffer": False,
                   "nearest_charted_danger_in_scope_m": 500}]}
        result = build(paired, closure, enc)
        self.assertEqual(result["camera_outlines_without_mapped_100m_buffer_hits"], 1)
        self.assertFalse(result["review_order"][0]["mllw_depth_qualified"])
        self.assertFalse(result["exportable"])
        bad = copy.deepcopy(closure)
        bad["outlines"][0]["native_200_300ft_navd88_cells"] = 9
        with self.assertRaises(ValueError):
            build(paired, bad, enc)


if __name__ == "__main__":
    unittest.main()

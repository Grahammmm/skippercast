import json
from pathlib import Path
import unittest

import numpy as np

from scripts.audit_point_conception_original_300_gap import summarize_cells


ROOT = Path(__file__).resolve().parents[1]


class PointConceptionOriginal300GapTests(unittest.TestCase):
    def test_scan_excludes_fill_and_counts_true_deeper_cells(self):
        elevation = np.array([[-20, -60.96, -91.44, 1000000],
                              [np.nan, -40, -92, -5]], dtype="float32")
        uncertainty = np.array([[.2, .3, .4, 1000000],
                                [.2, .5, np.nan, 0]], dtype="float32")
        result = summarize_cells(elevation, uncertainty,
                                 fill_elevation=1000000, fill_uncertainty=1000000)
        self.assertEqual(result["valid_elevation_cells"], 6)
        self.assertEqual(result["valid_depth_and_uncertainty_cells"], 4)
        self.assertEqual(result["200_to_300ft_depth_cells"], 2)
        self.assertEqual(result["deeper_than_200ft_cells"], 3)

    def test_exact_files_are_not_deeper_source_leads(self):
        receipt = json.loads((ROOT / "dist/data/point-conception-original-bag-200-300ft-gap.json").read_text())
        self.assertEqual(receipt["scope"], "point-conception-two-original-noaa-bags-200-300ft-exact-file-gap")
        self.assertEqual({row["survey_id"] for row in receipt["sources"]}, {"H11952", "H11953"})
        self.assertEqual(receipt["combined_200_to_300ft_cells"], 0)
        self.assertEqual([row["valid_depth_m_range"][1] for row in receipt["sources"]], [40.0, 20.0])
        self.assertTrue(all(row["vertical_datum"] == "MLLW" for row in receipt["sources"]))
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])


if __name__ == "__main__":
    unittest.main()

"""Keep the Lopez historical ROV receipt out of fishing and export layers."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BigCreekRovOriginalCellsTest(unittest.TestCase):
    def test_research_receipt_has_disjoint_source_tiers_and_no_positions(self):
        report = json.loads((ROOT / "dist/data/bigcreek-lopez-rov-original-cell-join.json").read_text())
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertFalse(report["chart_mllw_depth_and_upper_uncertainty_verified"])
        self.assertFalse(report["rov_bottom_position_error_bounded"])
        self.assertEqual(report["distinct_transect_labels_outside_screen"], 6)
        classes = report["outside_screen_by_derived_class"]
        self.assertEqual(sum(value["subunits"] for value in classes.values()),
                         report["counts"]["outside_mpa_plus_75m_screen"])
        self.assertEqual(sum(value.get("grid_2m_subunits", 0) + value.get("grid_5m_subunits", 0)
                             for value in classes.values()),
                         report["counts"]["outside_mpa_plus_75m_screen"])
        self.assertNotIn("coordinates", report)
        self.assertNotIn("features", report)
        self.assertNotIn("waypoints", report)


if __name__ == "__main__":
    unittest.main()

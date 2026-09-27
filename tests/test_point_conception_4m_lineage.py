import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PointConceptionFourMeterLineageTests(unittest.TestCase):
    def test_original_datum_uncertainty_and_class_dependence_are_explicit(self):
        report = json.loads((ROOT / "dist/data/point-conception-original-4m-source-lineage.json").read_text())
        self.assertEqual(report["scope"], "point-conception-two-original-4m-patches-noaa-usgs-lineage")
        self.assertEqual(report["usgs_map_report"]["reported_acoustic_source"],
                         "Fugro Pelagos bathymetry and backscatter collected in 2008")
        self.assertIn("not established", report["usgs_character"]["source_independence_from_noaa_bag"])
        self.assertEqual(len(report["components"]), 2)
        self.assertEqual([row["measured_depth_mllw_m"]["minimum"] for row in report["components"]],
                         [69.408, 61.046])
        self.assertEqual([row["measured_depth_mllw_m"]["maximum"] for row in report["components"]],
                         [73.473, 62.32])
        self.assertTrue(all(row["original_bag_metadata"]["embedded_vertical_datum"] == "MLLW"
                            and row["original_bag_metadata"]["embedded_uncertainty_type"] == "productUncert"
                            and row["survey_processing"]["historical_fieldsheet_4m_depth_range_m_reported"] == [80, 100]
                            and row["fishing_target"] is False and row["exportable"] is False
                            for row in report["components"]))
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertNotIn("geometry", report)
        self.assertNotIn("coordinates", report)


if __name__ == "__main__":
    unittest.main()

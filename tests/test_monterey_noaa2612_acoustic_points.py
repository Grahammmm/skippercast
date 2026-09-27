"""Point-cloud support cannot silently become a deeper fishing target."""

import json
from pathlib import Path
import unittest

from scripts.build_central_300_qualification_plan import build


ROOT = Path(__file__).resolve().parents[1]


class AcousticPointGate(unittest.TestCase):
    def test_measured_support_keeps_chart_depth_and_rank_unqualified(self):
        report = json.loads((ROOT / "dist/data/monterey-noaa2612-acoustic-point-support.json").read_text())
        self.assertEqual(report["outlines_reviewed"], 17)
        self.assertEqual(report["outlines_with_class13_points"], 17)
        self.assertEqual(report["camera_positive_outlines_with_class13_points"], 4)
        self.assertEqual(report["point_vertical_crs"], "EPSG:5703 NAVD88 height")
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        for row in report["outlines"]:
            self.assertFalse(row["mllw_depth_qualified"])
            self.assertFalse(row["upper_vertical_error_qualified"])
            self.assertFalse(row["independent_survey_qualified"])
            self.assertFalse(row["fishing_target"])
        camera = {row["context_id"][-3:]: row for row in report["outlines"]
                  if row["historical_rockfish_positive_windows"]}
        self.assertEqual(len(camera), 4)
        self.assertGreater(camera["023"]["class13_nominal_200_300ft_navd88_points"], 1000)
        self.assertGreater(camera["046"]["class13_nominal_200_300ft_navd88_points"], 1000)
        self.assertTrue(camera["001"]["prior_mapped_mpa_or_gea_review_hold"])
        self.assertTrue(camera["001"]["prior_enc_danger_review_hold"])

    def test_plan_keeps_point_receipt_on_research_side(self):
        sector = next(row for row in build(ROOT)["sectors"] if row["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-noaa2612-acoustic-point-support.json", sector["source_receipts"])
        self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)
        self.assertIsNone(sector["fishing_rank"])


if __name__ == "__main__":
    unittest.main()

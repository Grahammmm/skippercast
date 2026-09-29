"""Original EM300 discovery cannot satisfy an unknown-datum depth gate."""

import json
import unittest

from research.scripts.build_central_300_qualification_plan import build
from research.lib.receipts import RECEIPTS
from research.lib.paths import ROOT


class EM300ResearchGate(unittest.TestCase):
    def test_original_overlap_is_not_a_fishing_spot(self):
        report = json.loads((RECEIPTS / "monterey-1998-original-em300-overlap.json").read_text())
        self.assertEqual(report["outlines_with_original_cells"], 7)
        self.assertEqual(report["rockfish_camera_positive_outlines_with_original_cells"], 1)
        self.assertEqual(report["previously_uncovered_camera_outline_001"]["populated_cells"], 972)
        self.assertEqual(report["previously_uncovered_camera_outline_001"]["nominal_200_300ft_cells_unknown_datum"], 0)
        self.assertTrue(report["previously_uncovered_camera_outline_001"]["existing_mpa_or_gea_review_hold"])
        self.assertTrue(report["previously_uncovered_camera_outline_001"]["existing_enc_danger_review_hold"])
        self.assertFalse(report["original_vertical_datum_documented"])
        self.assertFalse(report["original_upper_vertical_error_documented"])
        self.assertFalse(report["independence_from_2016_composite_established"])
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])

    def test_new_receipt_does_not_promote_depth_gate(self):
        plan = build(ROOT)
        sector = next(row for row in plan["sectors"] if row["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-1998-original-em300-overlap.json", sector["source_receipts"])
        self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)
        self.assertTrue(all(not track["release_gate_satisfied"] for track in sector["tracks"]
                            if track["id"] in plan["release_gate_ids"]))


if __name__ == "__main__":
    unittest.main()

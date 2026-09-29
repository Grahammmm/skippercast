"""A historical cross-survey overlap cannot promote fishing marks."""

import json
from pathlib import Path
import unittest

from research.scripts.build_central_300_qualification_plan import build
from research.lib.receipts import RECEIPTS


ROOT = Path(__file__).resolve().parents[1]


class OriginalMultibeamResearchGate(unittest.TestCase):
    def test_unbounded_old_depth_stays_research_only(self):
        receipt = json.loads((RECEIPTS / "monterey-1995-original-multibeam-overlap.json").read_text())
        self.assertEqual(receipt["outlines_with_original_cells"], 14)
        self.assertEqual(receipt["rockfish_camera_positive_outlines_with_original_cells"], 3)
        self.assertFalse(receipt["original_vertical_datum_documented"])
        self.assertFalse(receipt["original_upper_vertical_error_documented"])
        self.assertFalse(receipt["independence_from_2016_composite_established"])
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        self.assertEqual(sum(row["large_difference_over_5m"] for row in receipt["outlines"]), 1)

    def test_plan_keeps_all_deeper_gates_closed(self):
        plan = build(ROOT)
        monterey = next(row for row in plan["sectors"] if row["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-1995-original-multibeam-overlap.json", monterey["source_receipts"])
        self.assertTrue(all(not track["release_gate_satisfied"] for track in monterey["tracks"]
                            if track["id"] in plan["release_gate_ids"]))


if __name__ == "__main__":
    unittest.main()

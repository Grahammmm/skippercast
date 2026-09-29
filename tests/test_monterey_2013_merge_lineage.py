"""The USGS Monterey resample cannot be counted as independent sounding TPU."""

import json
from pathlib import Path
import unittest

from research.scripts.build_central_300_qualification_plan import build


ROOT = Path(__file__).resolve().parents[1]


class MergeLineageGate(unittest.TestCase):
    def test_missing_accuracy_layer_keeps_depth_unqualified(self):
        report = json.loads((ROOT / "dist/data/monterey-2013-merge-lineage-gap.json").read_text())
        self.assertIn("resampled to 2 m", report["usgs_2m_source"])
        self.assertFalse(report["public_accuracy_layer_at_research_cells_obtained"])
        self.assertFalse(report["public_source_inventory_at_research_cells_obtained"])
        self.assertFalse(report["usgs_20cm_phrase_is_conservative_upper_bound"])
        self.assertFalse(report["independent_of_1995_or_1998_survey_established"])
        self.assertFalse(report["chart_datum_depth_qualified"])
        self.assertFalse(report["fishing_target"])

    def test_qualification_plan_tracks_original_noaa_deliverables(self):
        plan = build(ROOT)
        sector = next(item for item in plan["sectors"] if item["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-2013-merge-lineage-gap.json", sector["source_receipts"])
        self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)


if __name__ == "__main__":
    unittest.main()

"""A cruise footprint or centerline is not a measured 300-foot fishing patch."""

import json
from pathlib import Path
import unittest

from research.scripts.build_central_300_qualification_plan import build


ROOT = Path(__file__).resolve().parents[1]


class NceiTracklineGate(unittest.TestCase):
    def test_priority_source_discovery_does_not_qualify_depth(self):
        report = json.loads((ROOT / "dist/data/monterey-17-ncei-trackline-leads.json").read_text())
        self.assertEqual(report["outlines_reviewed"], 17)
        self.assertEqual(report["camera_positive_outlines_with_2009_central_monterey_trackline"], 2)
        rows = {row["context_id"][-3:]: row for row in report["outlines"]}
        for ident in ("023", "046"):
            self.assertEqual(rows[ident]["trackline_survey_ids"], ["CentralMontereyBay"])
            self.assertIn("MV1405", rows[ident]["footprint_only_survey_ids"])
        self.assertFalse(report["fishing_target"])
        for row in rows.values():
            self.assertFalse(row["survey_has_native_200_300ft_cells_verified"])
            self.assertFalse(row["chart_datum_and_upper_error_verified"])
            self.assertFalse(row["fishing_target"])

    def test_plan_tracks_source_lead_with_zero_new_ranks(self):
        sector = next(item for item in build(ROOT)["sectors"] if item["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-17-ncei-trackline-leads.json", sector["source_receipts"])
        self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)
        self.assertIsNone(sector["fishing_rank"])


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import unittest

from research.scripts import audit_point_buchon_a3_trackline_lineage as audit


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonA3TracklineLineageTests(unittest.TestCase):
    def test_delivery_year_is_not_assigned_to_candidate_cells(self):
        report = json.loads((ROOT / "dist/data/point-buchon-block-a3-trackline-lineage.json").read_text())
        self.assertEqual(report["trackline_member_sha256"], audit.TRACKLINES_SHA256)
        self.assertEqual(report["tracklines"]["bathy"]["count"], 112)
        self.assertEqual(report["tracklines"]["bathy"]["date_counts"], {
            "24 Oct 2007": 72, "25 Oct 2007": 20, "26 Oct 2007": 20})
        self.assertEqual(report["tracklines"]["all"]["count"], 113)
        self.assertFalse(report["catalog_2009_survey_intersects_envelope"])
        self.assertFalse(report["cell_acquisition_year_verified"])
        self.assertFalse(report["source_line_to_grid_cell_crosswalk_verified"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertFalse(report["exportable"])

    def test_original_trackline_package_still_matches(self):
        archive = ROOT / "var/review/point-buchon-additional-products/Pt_Buchon_control_additional_products.tar.gz"
        if not archive.exists():
            self.skipTest("Monthly job downloads original NOAA archive before full source audit")
        report = json.loads((ROOT / "dist/data/point-buchon-block-a3-trackline-lineage.json").read_text())
        self.assertEqual(audit.trackline_summary(archive), report["tracklines"])

    def test_retrieval_time_does_not_hide_lineage_change(self):
        report = json.loads((ROOT / "dist/data/point-buchon-block-a3-trackline-lineage.json").read_text())
        changed = {**report, "checked_at": "later"}
        self.assertEqual(audit.stable(report), audit.stable(changed))
        changed["cell_acquisition_year_verified"] = True
        self.assertNotEqual(audit.stable(report), audit.stable(changed))


if __name__ == "__main__":
    unittest.main()

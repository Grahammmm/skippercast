import io
import json
import unittest
from pathlib import Path

from scripts.audit_usgs_estero_2012_original import BANDS, header

ROOT = Path(__file__).resolve().parents[1]


class UsgsEstero2012OriginalTest(unittest.TestCase):
    def test_original_grid_layout_rejects_partial_header(self):
        valid = b"ncols 11456\nnrows 16020\nxllcorner 665810\nyllcorner 3900238\ncellsize 2\nNODATA_value -9999\n"
        self.assertEqual(header(io.BytesIO(valid))["ncols"], 11456)
        with self.assertRaisesRegex(ValueError, "layout changed"):
            header(io.BytesIO(valid.replace(b"ncols 11456", b"ncols 100")))

    def test_published_original_audit_preserves_gaps_and_holds(self):
        report = json.loads((ROOT / "dist/data/usgs-estero-bay-2012-original-200-300ft-review.json").read_text())
        self.assertEqual(BANDS, ((200, 250), (250, 300)))
        self.assertEqual(report["source_vertical_datum"], "NAVD88 Geoid12 for NAD83 bathymetry")
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertEqual(report["qualified_waypoints"], 0)
        for item in report["nominal_depth_bands"].values():
            self.assertGreater(item["depth_cells"], item["paired_nominal_cells"])

    def test_independent_character_overlap_is_only_nominal(self):
        report = json.loads((ROOT / "dist/data/estero-independent-2012-depth-2008-character-overlap.json").read_text())
        self.assertFalse(report["fishing_target"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertGreater(report["depth_bands"]["250-300ft"]["classified_cells_by_type"]["hard_rugose"], 0)
        self.assertIn("Nominal", report["limitations"][0])


if __name__ == "__main__":
    unittest.main()

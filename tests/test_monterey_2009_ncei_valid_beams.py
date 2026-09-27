"""Original valid sounding counts remain research evidence until datum is known."""

import json
from pathlib import Path
import unittest

from scripts.build_central_300_qualification_plan import build


ROOT = Path(__file__).resolve().parents[1]


class OriginalBeamGate(unittest.TestCase):
    def test_priority_beams_have_unknown_tidal_datum(self):
        report = json.loads((ROOT / "dist/data/monterey-2009-centralmontereybay-valid-beam-review.json").read_text())
        self.assertEqual(report["processed_files_audited"], 5)
        self.assertIn("TIDAL_DATUM=UNKNOWN", report["processing_parameters_common"])
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        for ident, count in (("023", 314362), ("046", 72083)):
            row = report["outlines"][ident]
            self.assertEqual(row["valid_beams_inside_outline"], count)
            self.assertEqual(row["valid_beams_nominal_200_300ft_unknown_datum"], count)
            self.assertFalse(row["mllw_depth_qualified"])
            self.assertFalse(row["upper_vertical_error_qualified"])
            self.assertFalse(row["fishing_target"])
            self.assertFalse(row["exportable"])
        for line in report["lines"]:
            self.assertTrue(line["generated_companion_checks"]["generated_inf_good_beams_match"])
            self.assertTrue(line["generated_companion_checks"]["generated_fnv_navigation_rows_match"])
            self.assertGreaterEqual(line["counts"]["beam_flags_good_including_ignored_pings"],
                                    line["counts"]["valid_unflagged_beams"])

    def test_plan_has_receipt_and_no_rank(self):
        sector = next(row for row in build(ROOT)["sectors"] if row["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-2009-centralmontereybay-valid-beam-review.json", sector["source_receipts"])
        self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)
        self.assertIsNone(sector["fishing_rank"])


if __name__ == "__main__":
    unittest.main()

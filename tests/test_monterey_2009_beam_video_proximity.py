"""A historically close camera window is not current catch evidence."""

import json
from pathlib import Path
import unittest

from research.scripts.build_central_300_qualification_plan import build
from research.lib.receipts import RECEIPTS


ROOT = Path(__file__).resolve().parents[1]


class HistoricalCameraGate(unittest.TestCase):
    def test_old_rockfish_windows_do_not_promote_fishing_marks(self):
        report = json.loads((RECEIPTS / "monterey-2009-beam-2010-video-proximity.json").read_text())
        self.assertEqual(report["scope"], "monterey-2009-beam-to-2010-video-proximity-research")
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        for ident, windows in (("023", 5), ("046", 2)):
            row = report["outlines"][ident]
            self.assertEqual(row["interior_camera_windows"], windows)
            self.assertEqual(row["rock_boulder_cobble_windows"], windows)
            self.assertEqual(row["rockfish_positive_windows"], 1)
            self.assertEqual(row["distinct_camera_transects"], 1)
            self.assertEqual(row["camera_windows_with_valid_2009_beam_within_2m"], windows)
            self.assertFalse(row["independent_current_fish_presence_qualified"])
            self.assertFalse(row["fishing_target"])
            self.assertFalse(row["exportable"])

    def test_plan_retains_camera_receipt_without_rank(self):
        sector = next(row for row in build(ROOT)["sectors"] if row["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-2009-beam-2010-video-proximity.json", sector["source_receipts"])
        self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)
        self.assertIsNone(sector["fishing_rank"])


if __name__ == "__main__":
    unittest.main()

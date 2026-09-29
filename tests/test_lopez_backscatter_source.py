"""Original acoustic imagery stays a held source, not a fishing layer."""

import json
from pathlib import Path
import unittest

from skippercast.platform.candidate import validate_candidate
from research.lib.receipts import RECEIPTS


ROOT = Path(__file__).resolve().parents[1]


class LopezBackscatterSourceTest(unittest.TestCase):
    def test_two_native_mosaics_are_cataloged_with_release_holds(self):
        report = json.loads((RECEIPTS / "lopez-original-backscatter-source-review.json").read_text())
        self.assertEqual({row["sensor"] for row in report["mosaics"]},
                         {"reson_7125", "sea_swathplus"})
        self.assertTrue(all(row["resolution_m"] == 1 and row["declared_nodata"] is None
                            and row["mask_flags"] == ["all_valid"]
                            for row in report["mosaics"]))
        self.assertFalse(report["backscatter_to_rock_calibration_verified"])
        self.assertFalse(report["valid_backscatter_footprint_verified"])
        self.assertFalse(report["bathymetry_horizontal_realization_verified_from_this_source"])
        self.assertFalse(report["public_redistribution_rights_verified"])
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        candidate = json.loads((ROOT / "catalog/candidates/csumb-lopez-original-backscatter.json").read_text())
        self.assertFalse(validate_candidate(candidate)["publication_approved"])


if __name__ == "__main__":
    unittest.main()

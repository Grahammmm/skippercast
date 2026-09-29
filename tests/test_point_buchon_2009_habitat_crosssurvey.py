import json
from pathlib import Path
import unittest

from research.scripts import audit_point_buchon_2009_habitat_crosssurvey as audit


ROOT = Path(__file__).resolve().parents[1]


class PointBuchon2009HabitatCrossSurveyTests(unittest.TestCase):
    def test_cross_survey_terrain_agreement_does_not_claim_rock_or_fish(self):
        receipt = json.loads((ROOT / "dist/data/point-buchon-2009-csumb-terrain-crosssurvey.json").read_text())
        self.assertEqual(receipt["inner_member_sha256"], audit.MEMBER_SHA256)
        self.assertEqual(receipt["usgs_hard_rugose_cells_with_csumb_class"], 87115)
        self.assertEqual(receipt["usgs_hard_rugose_cells_also_csumb_rough"], 66133)
        self.assertFalse(receipt["independent_rock_groundtruth"])
        self.assertFalse(receipt["depth_mllw_and_upper_uncertainty_verified"])
        self.assertFalse(receipt["cross_survey_registration_verified"])
        self.assertFalse(receipt["reuse_rights_resolved"])
        self.assertEqual(receipt["qualified_waypoints"], 0)
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])

    def test_original_archive_reaudit_matches_published_receipt(self):
        archive = ROOT / "var/review/point-buchon-additional-products/Pt_Buchon_control_additional_products.tar.gz"
        character = ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip"
        if not archive.exists() or not character.exists():
            self.skipTest("Monthly source job downloads original archives before full audit")
        expected = json.loads((ROOT / "dist/data/point-buchon-2009-csumb-terrain-crosssurvey.json").read_text())
        self.assertEqual(audit.audit(archive, character), expected)


if __name__ == "__main__":
    unittest.main()

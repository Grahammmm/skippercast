"""Point Arena regional preview must not turn source leads into fishing marks."""
import json
from pathlib import Path
import unittest

from scripts.prepare_regional_mpas import validate_response
from skippercast.pipeline.settings import settings


ROOT = Path(__file__).resolve().parents[1]
RID = "point-arena-bodega"


class PointArenaBodegaTests(unittest.TestCase):
    def test_mpas_and_preview_are_bounded_and_unqualified(self):
        region = json.loads((ROOT / "regions" / RID / "region.json").read_text())
        mpa = json.loads((ROOT / "dist" / region["assets"]["protected_areas"]).read_text())
        atlas = json.loads((ROOT / "dist" / region["assets"]["atlas"]).read_text())
        self.assertEqual(len(validate_response(mpa, region["mpa"]["bounds"], 11)), 11)
        self.assertEqual(region["status"], "preview")
        self.assertEqual(atlas["region_id"], RID)
        self.assertEqual((atlas["targets"], atlas["areas"], atlas["drifts"]), ([], [], []))

    def test_local_rules_have_a_reviewed_source_for_each_mpa_group(self):
        config = settings(RID)
        rules = config["regulations"]
        decision = json.loads((ROOT / rules["review_record"]).read_text())
        self.assertEqual(decision["rules_content_sha256"], rules["approved_rules_content_sha256"])
        for ident in ("mpa-point-arena-sea-lion", "mpa-saunders", "mpa-del-mar",
                      "mpa-stewarts", "mpa-salt-gerstle", "mpa-russian-river"):
            self.assertIn(ident, config["watches"])
            self.assertEqual(decision["sources"][ident]["decision"], "approve")
        self.assertNotIn("salmon", config["region"]["map"]["unavailable_targets"])


if __name__ == "__main__":
    unittest.main()

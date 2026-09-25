"""Point Arena regional preview must not turn source leads into fishing marks."""
import json
import hashlib
from pathlib import Path
import unittest

from shapely.geometry import shape
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

    def test_original_cell_context_is_research_only_and_outside_mpas(self):
        region = json.loads((ROOT / "regions" / RID / "region.json").read_text())
        report = json.loads((ROOT / "dist/data/arena-native-hard-terrain-review.json").read_text())
        source_path = ROOT / "dist/data/sf-native-hard-context.geojson"
        layer = json.loads((ROOT / "dist" / region["assets"]["survey_habitat"]).read_text())
        mpas = json.loads((ROOT / "dist" / region["assets"]["protected_areas"]).read_text())
        self.assertEqual(report["source_context_sha256"], hashlib.sha256(source_path.read_bytes()).hexdigest())
        self.assertEqual(report["reviewed_outlines"], 56)
        self.assertEqual(report["terrain_reviewed"], 19)
        self.assertEqual(report["holds"], {"held-charted-danger-proximity": 1,
                                            "held-small-display": 36})
        self.assertEqual(layer["summary"], {"historical_research_outlines": 19,
                                             "fishing_targets": 0})
        self.assertEqual(len(layer["features"]), 19)
        for feature in layer["features"]:
            props = feature["properties"]
            self.assertFalse(props["fishing_target"])
            self.assertFalse(props["fishing_export"])
            self.assertFalse(props["bottom_view"])
            self.assertFalse(props["depth_qualified"])
            self.assertIsNone(props["quality_grade"])
            self.assertGreaterEqual(props["sampled_original_depth_ft"]["minimum"], 25)
            self.assertLessEqual(props["sampled_original_depth_ft"]["maximum"], 200)
            self.assertFalse(any(shape(feature["geometry"]).intersects(shape(m["geometry"]))
                                 for m in mpas["features"]))


if __name__ == "__main__":
    unittest.main()

"""Point Reyes preview keeps legal exclusions and uncertain terrain off exports."""
import json
from pathlib import Path
import unittest

from shapely.geometry import MultiPolygon, Polygon, mapping, shape

from scripts.prepare_regional_mpas import validate_response
from skippercast.pipeline.settings import settings


ROOT = Path(__file__).resolve().parents[1]
RID = "point-reyes-pigeon"


class PointReyesPigeonTests(unittest.TestCase):
    def test_official_mpa_snapshot_preserves_farallon_closures(self):
        region = json.loads((ROOT / "regions" / RID / "region.json").read_text())
        snapshot = json.loads((ROOT / "dist" / region["assets"]["protected_areas"]).read_text())
        self.assertEqual(snapshot["region_id"], RID)
        self.assertEqual(len(validate_response(snapshot, region["mpa"]["bounds"], 14)), 14)
        repaired = {f["properties"]["NAME"] for f in snapshot["features"]
                    if f["properties"].get("geometry_repair")}
        self.assertEqual(repaired, set(region["mpa"]["conservative_union_invalid_names"]))

    def test_nested_closure_repair_is_explicit_and_conservative(self):
        outer = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
        inner = Polygon([(1, 1), (2, 1), (2, 2), (1, 2)])
        original = MultiPolygon([outer, inner])
        self.assertFalse(original.is_valid)
        feature = {"type": "Feature", "properties": {"NAME": "Example Special Closure"},
                   "geometry": mapping(original)}
        data = {"type": "FeatureCollection", "features": [feature]}
        with self.assertRaises(ValueError):
            validate_response(json.loads(json.dumps(data)), [-1, -1, 5, 5], 1)
        result = validate_response(data, [-1, -1, 5, 5], 1,
                                   ("Example Special Closure",))
        repaired = shape(result[0]["geometry"])
        self.assertTrue(repaired.is_valid)
        self.assertTrue(repaired.covers(outer))
        self.assertTrue(repaired.covers(inner))
        self.assertEqual(result[0]["properties"]["original_component_count"], 2)

    def test_preview_has_no_unqualified_marks_or_exports(self):
        region = json.loads((ROOT / "regions" / RID / "region.json").read_text())
        atlas = json.loads((ROOT / "dist" / region["assets"]["atlas"]).read_text())
        self.assertEqual(region["status"], "preview")
        self.assertEqual(atlas["region_id"], RID)
        self.assertEqual(atlas["targets"], [])
        self.assertEqual(atlas["areas"], [])
        self.assertEqual(atlas["drifts"], [])

    def test_local_rules_review_is_hash_bound(self):
        config = settings(RID)
        rules = config["regulations"]
        decision = json.loads((ROOT / rules["review_record"]).read_text())
        self.assertEqual(decision["rules_content_sha256"],
                         rules["approved_rules_content_sha256"])
        self.assertEqual(set(decision["reviewed_species"]),
                         {"lingcod", "rockfish", "halibut", "salmon", "dungeness", "albacore"})
        self.assertEqual(len(decision["sources"]), 30)
        self.assertIn("mpa-montara-pillar", config["watches"])
        self.assertIn("mpa-north-farallon", config["watches"])
        self.assertNotIn("access-vandenberg-maritime", config["watches"])


if __name__ == "__main__":
    unittest.main()

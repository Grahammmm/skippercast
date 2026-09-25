"""Shelter Cove release gates: exact MPAs, zero targets and source-checked rules."""
import json
from pathlib import Path
import unittest

from scripts.prepare_regional_mpas import validate_response


ROOT = Path(__file__).resolve().parents[1]
RID = "shelter-cove-north-mendocino"


class ShelterCoveRegionTests(unittest.TestCase):
    def test_local_mpa_snapshot_has_all_discovered_protections(self):
        region = json.loads((ROOT / "regions" / RID / "region.json").read_text())
        snapshot = json.loads((ROOT / "dist" / region["assets"]["protected_areas"]).read_text())
        self.assertEqual(snapshot["region_id"], RID)
        self.assertEqual(region["mpa"]["minimum_features"], 7)
        validate_response(snapshot, region["mpa"]["bounds"], 7)
        names = {f["properties"]["NAME"] for f in snapshot["features"]}
        self.assertEqual(names, {
            "Big Flat SMCA", "Double Cone Rock SMCA", "Vizcaino Rock Special Closure",
            "Ten Mile SMR", "Ten Mile Beach SMCA", "Ten Mile Estuary SMCA", "MacKerricher SMCA",
        })
        self.assertTrue(snapshot["source_url"].startswith("https://services2.arcgis.com/"))

    def test_preview_has_no_fishing_or_export_geometry(self):
        region = json.loads((ROOT / "regions" / RID / "region.json").read_text())
        atlas = json.loads((ROOT / "dist" / region["assets"]["atlas"]).read_text())
        self.assertEqual(region["status"], "preview")
        self.assertEqual(atlas["region_id"], RID)
        for key in ("targets", "areas", "drifts"):
            self.assertEqual(atlas[key], [])
        self.assertIsNone(region["assets"].get("ais_evidence"))

    def test_local_rule_sources_are_hash_reviewed(self):
        region = json.loads((ROOT / "regions" / RID / "region.json").read_text())
        rules = json.loads((ROOT / "dist" / region["assets"]["regulations"]).read_text())
        decision = json.loads((ROOT / rules["review_record"]).read_text())
        self.assertEqual(decision["rules_content_sha256"], rules["approved_rules_content_sha256"])
        self.assertIn({"id": RID, "fishing_bounds": region["fishing_bounds"]}, decision["reviewed_regions"])
        notice = next(n for n in rules["area_notices"] if n["id"] == "north-mendocino-mpas")
        self.assertEqual(set(notice["source_ids"]), {
            "mpa-big-flat", "mpa-ten-mile", "mpa-double-cone",
            "closure-vizcaino-rock", "mpa-mackerricher",
        })
        self.assertTrue(all(decision["sources"][source]["decision"] == "approve" for source in notice["source_ids"]))

    def test_incomplete_mpa_response_is_rejected(self):
        bounds = [-124.8, 39.45, -123.6, 40.166666666666664]
        with self.assertRaises(ValueError):
            validate_response({"type": "FeatureCollection", "features": [], "exceededTransferLimit": True}, bounds, 7)


if __name__ == "__main__":
    unittest.main()

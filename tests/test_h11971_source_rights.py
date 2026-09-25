"""Keep source-use evidence distinct from fishing-target qualification."""
import json
from pathlib import Path
import unittest

from scripts.audit_noaa_usgs_camera_rights import audit


ROOT = Path(__file__).resolve().parents[1]


class H11971SourceRightsTest(unittest.TestCase):
    def test_reviewed_rights_do_not_promote_historical_camera_points(self):
        receipt = json.loads((ROOT / "dist/data/h11971-camera-source-rights-review.json").read_text())
        candidate = json.loads((ROOT / "catalog/candidates/noaa-h11971-bear-landing-original-camera.json").read_text())
        readiness = json.loads((ROOT / "dist/data/california-atlas-readiness.json").read_text())
        self.assertTrue(candidate["rights"]["redistribution_reviewed"])
        self.assertEqual(candidate["rights"]["terms_url"], receipt["usgs_camera_metadata_url"])
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        self.assertIn("Credit the U.S. Geological Survey in derived products", receipt["use_conditions"])
        self.assertIn("Share derived data products with the U.S. Geological Survey", receipt["use_conditions"])
        self.assertIn("shelter-cove-north-mendocino", json.dumps(readiness))

    def test_missing_official_use_condition_fails_closed(self):
        noaa = b"H11971 Creative Commons Zero 1.0 Universal Public Domain Dedication (CC0-1.0) NOAA waives any potential copyright"
        usgs = (b"C210NC_video_observations Access_Constraints: None "
                b"This information is not intended for navigational purposes. "
                b"Acknowledge the U.S. Geological Survey in products derived from these data.")
        with self.assertRaisesRegex(ValueError, "use conditions changed"):
            audit("H11971", "c210nc", noaa, usgs)


if __name__ == "__main__":
    unittest.main()

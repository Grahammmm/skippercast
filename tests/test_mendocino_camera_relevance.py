"""Broad H11730 survey coverage must not become local camera evidence."""
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MendocinoCameraRelevanceTests(unittest.TestCase):
    def test_original_camera_windows_do_not_support_fort_bragg_sites(self):
        packet = json.loads((ROOT / "dist/data/h11730-fort-bragg-regional-camera-support.json").read_text())
        candidate = json.loads((ROOT / "catalog/candidates/noaa-h11730-arena-bodega-original-camera.json").read_text())
        sources = [ROOT / "regions/fort-bragg-point-arena/region.json",
                   ROOT / "dist/data/noaa-statewide-regular-camera-review.json"]
        self.assertEqual(packet["region_id"], "fort-bragg-point-arena")
        self.assertEqual(packet["survey_id"], "H11730")
        self.assertEqual(packet["region_sha256"], hashlib.sha256(sources[0].read_bytes()).hexdigest())
        self.assertEqual(packet["pair_review_sha256"], hashlib.sha256(sources[1].read_bytes()).hexdigest())
        self.assertEqual(packet["distinct_camera_windows"], 110)
        self.assertEqual(packet["windows_inside_region"], 0)
        self.assertEqual(set(packet["source_archives"]), {"f208nc", "c210nc"})
        self.assertFalse(packet["fishing_target"])
        self.assertFalse(packet["exportable"])
        self.assertNotIn("fort-bragg-arena", candidate["sector_ids"])


if __name__ == "__main__":
    unittest.main()

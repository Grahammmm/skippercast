import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_sansimeon_bedrock_overlap import fetch_geology


ROOT = Path(__file__).resolve().parents[1]


class SanSimeonBedrockReviewTest(unittest.TestCase):
    def test_research_receipt_cannot_be_mistaken_for_waypoints(self):
        manifest = json.loads((ROOT / "catalog/usgs-sansimeon-geology.json").read_text())
        self.assertFalse(set(manifest["pure_bedrock_units"]) &
                         set(manifest["composite_sediment_over_bedrock_units_excluded"]))
        review = json.loads((ROOT / "dist/data/csumb-sansimeon-bedrock-overlap-review.json").read_text())
        self.assertEqual(review["status"], "research-only")
        self.assertEqual(review["geology_source"]["sha256"], manifest["archive_sha256"])
        self.assertGreaterEqual(review["mpa_source"]["count"], 8)
        self.assertEqual(len(review["blocks"]), 3)
        self.assertNotIn("targets", review)
        for block in review["blocks"]:
            self.assertIn("no certified MLLW depth", block["publication_status"])
            self.assertNotIn("latitude", block)
            self.assertNotIn("longitude", block)
            self.assertLessEqual(block["outside_mpa_100m_buffer_cells"],
                                 block["pure_bedrock_inset_rough_nominal_navd_cells"])

    def test_changed_geology_archive_fails_closed(self):
        manifest = json.loads((ROOT / "catalog/usgs-sansimeon-geology.json").read_text())
        with tempfile.TemporaryDirectory() as cache:
            (Path(cache) / "Geology_SanSimeon.zip").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "archive digest changed"):
                fetch_geology(manifest, Path(cache), False)


if __name__ == "__main__":
    unittest.main()

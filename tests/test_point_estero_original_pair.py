import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_point_estero_original_pair import BANDS, CLASSES, PIN, checked


class PointEsteroOriginalPairTest(unittest.TestCase):
    def test_depth_bands_and_character_are_specific(self):
        self.assertEqual(BANDS, ((200, 250), (250, 300)))
        self.assertEqual(CLASSES[2], "hard_flat")
        self.assertEqual(CLASSES[3], "hard_rugose")

    def test_changed_original_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            name = "SeafloorCharacter_OffshorePointEstero_metadata.xml"
            path = Path(folder) / name
            path.write_text("changed")
            self.assertIn(name, PIN)
            with self.assertRaisesRegex(ValueError, "official source changed"):
                checked(path)

    def test_published_review_cannot_export_a_mark(self):
        path = Path(__file__).resolve().parents[1] / "dist/data/point-estero-original-paired-200-300ft-review.json"
        if not path.exists():
            self.skipTest("Original audit not built yet")
        review = json.loads(path.read_text())
        self.assertFalse(review["fishing_target"])
        self.assertFalse(review["exportable"])
        self.assertEqual(review["qualified_waypoints"], 0)
        self.assertIsNone(review["native_depth_vertical_datum"])


if __name__ == "__main__":
    unittest.main()

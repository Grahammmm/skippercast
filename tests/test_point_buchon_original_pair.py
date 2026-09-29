import tempfile
import unittest
from pathlib import Path

from research.scripts.audit_point_buchon_original_pair import (
    CLASS_NAMES, published_character_accuracy, verify_bathy_processing, verify_semantics,
)


class PointBuchonOriginalPairTest(unittest.TestCase):
    def test_rock_classes_are_not_conflated(self):
        self.assertEqual(CLASS_NAMES[2], "hard_flat")
        self.assertEqual(CLASS_NAMES[3], "hard_rugose")

    def test_changed_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "metadata.xml"
            path.write_text("class 3 = fish here")
            with self.assertRaisesRegex(ValueError, "metadata changed"):
                verify_semantics(path)

    def test_bathymetry_processing_metadata_is_pinned(self):
        path = (Path(__file__).resolve().parents[1]
                / "var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon_metadata.xml")
        if not path.exists():
            self.skipTest("Original bathymetry metadata not fetched in this environment")
        self.assertEqual(len(verify_bathy_processing(path)), 64)

    def test_publisher_class_accuracy_is_not_a_holdout_probability(self):
        path = (Path(__file__).resolve().parents[1]
                / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon_metadata.xml")
        if not path.exists():
            self.skipTest("Original character metadata not fetched in this environment")
        accuracy = published_character_accuracy(path)
        self.assertEqual(accuracy["video_observations"], 304)
        self.assertEqual(accuracy["hard_flat"]["majority_percent"], 45.33)
        self.assertEqual(accuracy["hard_rugose"]["majority_percent"], 78.75)
        self.assertTrue(accuracy["training_observations_reused_for_accuracy"])
        self.assertFalse(accuracy["held_out_validation"])


if __name__ == "__main__":
    unittest.main()

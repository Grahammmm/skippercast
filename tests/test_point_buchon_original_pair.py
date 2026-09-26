import tempfile
import unittest
from pathlib import Path

from scripts.audit_point_buchon_original_pair import verify_semantics, verify_bathy_processing, CLASS_NAMES


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


if __name__ == "__main__":
    unittest.main()

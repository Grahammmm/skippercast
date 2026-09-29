import json
from pathlib import Path
import unittest
from research.lib.receipts import RECEIPTS


ROOT = Path(__file__).resolve().parents[1]


class PointConceptionFourMeterCameraGapTests(unittest.TestCase):
    def test_original_camera_proximity_does_not_verify_patch(self):
        report = json.loads((RECEIPTS / "point-conception-original-4m-camera-gap.json").read_text())
        self.assertEqual(report["scope"], "point-conception-two-original-4m-components-usgs-video-proximity")
        self.assertEqual(len(report["sources"]), 12)
        self.assertEqual([row["survey_id"] for row in report["components"]], ["H11952", "H11953"])
        self.assertEqual([row["bottom_observations_inside_component"] for row in report["components"]], [0, 0])
        self.assertEqual([row["nearest_camera_window_within_1000m_m"] for row in report["components"]], [745.1, 145.6])
        self.assertEqual(report["components"][1]["within_250m_distinct_transects"], 1)
        self.assertEqual(report["components"][1]["within_250m_bottom_classes"],
                         {"rock": 7, "mud": 14, "sand": 1})
        self.assertEqual(report["components"][1]["within_250m_rockfish_positive_windows"], 2)
        self.assertTrue(all(row["camera_verified_bottom"] is False and row["fishing_target"] is False
                            and row["exportable"] is False for row in report["components"]))
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertNotIn("geometry", report)
        self.assertNotIn("coordinates", report)


if __name__ == "__main__":
    unittest.main()

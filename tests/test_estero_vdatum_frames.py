import json
import unittest
from pathlib import Path

from scripts.audit_estero_vdatum_frames import classify

ROOT = Path(__file__).resolve().parents[1]


class EsteroVdatumFramesTest(unittest.TestCase):
    def test_api_rejection_does_not_become_offset(self):
        value = classify("WGS84_G1150", {"errorCode": 412,
                                          "message": "Source Horizontal Frame should be NAD83_2011"})
        self.assertEqual(value["status"], "rejected")
        self.assertNotIn("offset_m", value)

    def test_invalid_or_sentinel_result_fails(self):
        base = {"region": "WESTCOAST", "s_h_frame": "NAD83_2011",
                "s_v_frame": "NAVD88", "t_v_frame": "MLLW", "t_z": "-999999",
                "uncertainty": "0.1"}
        with self.assertRaisesRegex(ValueError, "sentinel"):
            classify("NAD83_2011", base)

    def test_public_receipt_has_no_grid_conversion_claim(self):
        report = json.loads((ROOT / "dist/data/estero-2012-vdatum-frame-review.json").read_text())
        self.assertFalse(report["mllw_raster_converted"])
        self.assertFalse(report["fishing_target"])
        results = {row["requested_horizontal_frame"]: row["status"] for row in report["samples"]}
        self.assertEqual(results["NAD83_2011"], "point_available")
        self.assertEqual(results["NAD83_CORS96"], "rejected")
        self.assertEqual(results["WGS84_G1150"], "rejected")


if __name__ == "__main__":
    unittest.main()

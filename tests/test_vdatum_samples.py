import unittest

from scripts.audit_vdatum_samples import assess_response


class VDatumSampleTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "region": "WESTCOAST", "s_h_frame": "NAD83_2011", "s_v_frame": "NAVD88",
            "s_v_unit": "m", "t_h_frame": "IGS14", "t_v_frame": "MLLW", "t_v_unit": "m",
            "s_x": "-121.95", "s_y": "36.64", "t_x": "-121.95001", "t_y": "36.640001",
            "t_z": "-0.039", "uncertainty": "0.094",
        }

    def test_valid_conversion_is_only_sample_available(self):
        self.assertEqual(assess_response(self.valid, -121.95, 36.64)["status"], "sample_available")

    def test_http_200_no_result_sentinel_is_unavailable(self):
        response = {**self.valid, "t_z": "-999999", "uncertainty": ""}
        self.assertEqual(assess_response(response, -121.95, 36.64)["status"], "unavailable")

    def test_wrong_tidal_frame_and_mismatched_point_are_rejected(self):
        self.assertEqual(assess_response({**self.valid, "t_h_frame": "NAD83_2011"}, -121.95, 36.64)["status"], "invalid_response")
        self.assertEqual(assess_response(self.valid, -121.94, 36.64)["status"], "invalid_response")


if __name__ == "__main__":
    unittest.main()

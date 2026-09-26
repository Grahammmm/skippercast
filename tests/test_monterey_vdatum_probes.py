import json
import unittest

from scripts.audit_monterey_vdatum_probes import parse, request_url


class VDatumProbeTests(unittest.TestCase):
    def setUp(self):
        self.lon, self.lat = -121.90359583, 36.67885983
        self.response = {
            "region": "WESTCOAST", "s_h_frame": "NAD83_2011", "s_coor": "geo",
            "s_v_frame": "NAVD88", "s_v_unit": "m", "s_v_elevation": "height",
            "t_h_frame": "IGS14", "t_coor": "geo", "t_v_frame": "MLLW",
            "t_v_unit": "m", "t_v_elevation": "height",
            "epoch_in": "0.0", "epoch_out": "0.0",
            "s_x": str(self.lon), "s_y": str(self.lat), "s_z": "0",
            "t_x": str(self.lon - 0.00002), "t_y": str(self.lat + 0.000002),
            "t_z": "-0.037", "uncertainty": "0.094",
        }

    def test_explicit_conditional_west_coast_route(self):
        url = request_url(self.lon, self.lat)
        self.assertIn("s_h_frame=NAD83_2011", url)
        self.assertIn("t_h_frame=IGS14", url)
        self.assertEqual(parse(json.dumps(self.response).encode(), self.lon, self.lat)
                         ["vdatum_reported_uncertainty_m"], 0.094)

    def test_api_error_or_missing_uncertainty_fails_closed(self):
        for response in ({"errorCode": 412, "message": "wrong frame"},
                         {**self.response, "uncertainty": ""},
                         {**self.response, "t_v_frame": "MHW"},
                         {**self.response, "epoch_out": "2020.0"}):
            with self.subTest(response=response), self.assertRaises((ValueError, KeyError)):
                parse(json.dumps(response).encode(), self.lon, self.lat)

    def test_outside_scope_rejected(self):
        with self.assertRaises(ValueError):
            request_url(-120.7, 36.7)


if __name__ == "__main__":
    unittest.main()

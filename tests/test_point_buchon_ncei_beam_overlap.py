import hashlib
import json
from pathlib import Path
import unittest

import numpy as np
from pyproj import Geod

from research.scripts import audit_point_buchon_ncei_beam_overlap as beams


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonValidBeamTest(unittest.TestCase):
    def test_ship_relative_beam_positions_follow_heading(self):
        geod = Geod(ellps="WGS84")
        lon, lat = beams.beam_positions(geod, -120.9, 35.2, 0,
                                        np.array([100., 0.]), np.array([0., 100.]))
        self.assertGreater(lon[0], -120.9)  # starboard of north-going ship is east
        self.assertAlmostEqual(lat[0], 35.2, places=5)
        self.assertGreater(lat[1], 35.2)
        lon, lat = beams.beam_positions(geod, -120.9, 35.2, 90,
                                        np.array([100., 0.]), np.array([0., 100.]))
        self.assertLess(lat[0], 35.2)  # starboard of east-going ship is south

    def test_original_beam_receipt_keeps_spots_unqualified(self):
        result = json.loads((ROOT / "dist/data/point-buchon-2007-ncei-valid-beam-overlap.json").read_text())
        self.assertEqual(result["scope"], "point-buchon-2007-ncei-original-valid-beam-overlap")
        self.assertEqual(result["qualified_waypoints"], 0)
        self.assertFalse(result["fishing_target"])
        self.assertFalse(result["exportable"])
        self.assertEqual({row["survey_id"] for row in result["surveys"]}, set(beams.PROBES))
        expected = {"PointBuchon": (280304, 558), "PointBuchon_Control": (712368, 13992)}
        for row in result["surveys"]:
            good, hard_pixels = expected[row["survey_id"]]
            self.assertEqual(row["valid_unflagged_beams"], good)
            self.assertEqual(row["unique_usgs_hard_rugose_200_300ft_pixels_under_valid_beams"], hard_pixels)
            self.assertTrue(row["generated_inf_good_beams_match"])
            self.assertTrue(row["generated_fnv_navigation_rows_match"])
            self.assertGreater(row["valid_beams_both_nominal_depth_bands_and_usgs_hard_rugose"], 0)

    def test_generated_companions_must_match_decoded_beams_and_navigation(self):
        inf = b"Number of Good Beams: 42"
        nav = (b"2007 05 09 22 45 39.684 1178750739.684 -120.9 35.2 158.2 "
               b"0 0 0 0 0 -120.89 35.21 -120.91 35.19\n")
        spec = {"inf_sha256": hashlib.sha256(inf).hexdigest(),
                "fnv_sha256": hashlib.sha256(nav).hexdigest()}
        found = beams.check_generated_companions(inf, nav, spec, [(-120.9, 35.2, 158.2)],
                                                 {"valid_unflagged_beams": 42, "ping_records": 1})
        self.assertTrue(found["generated_inf_good_beams_match"])
        with self.assertRaisesRegex(ValueError, "beam count"):
            beams.check_generated_companions(inf, nav, spec, [(-120.9, 35.2, 158.2)],
                                             {"valid_unflagged_beams": 41, "ping_records": 1})
        with self.assertRaisesRegex(ValueError, "ping position"):
            beams.check_generated_companions(inf, nav, spec, [(-120.8, 35.2, 158.2)],
                                             {"valid_unflagged_beams": 42, "ping_records": 1})


if __name__ == "__main__":
    unittest.main()

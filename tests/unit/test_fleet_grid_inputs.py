"""RF0740-7: ``grid_cell`` refuses a point or cell edge it cannot bin with a named ValueError.

Valid inputs must give exactly the tuples main's formula gave (cell ids are stored).
Points are synthetic positions off the California coast; no AIS data.
"""
import math
import unittest

from skippercast.fleet.ais.aggregate import grid_cell
from skippercast.fleet.ais.simplify import METRES_PER_DEG


def main_formula(lat, lon, resolution_m):
    """grid_cell's arithmetic as on main before RF0740-7 (reference copy)."""
    d_lat = resolution_m / METRES_PER_DEG
    row = math.floor(lat / d_lat)
    centre_lat = (row + 0.5) * d_lat
    d_lon = resolution_m / (METRES_PER_DEG * max(math.cos(math.radians(centre_lat)), 0.01))
    col = math.floor(lon / d_lon)
    centre_lon = (col + 0.5) * d_lon
    return f"g{resolution_m:g}:{row}:{col}", centre_lat, centre_lon


class Refused(unittest.TestCase):
    def assertRefused(self, args, message):
        with self.assertRaises(ValueError) as caught:
            grid_cell(*args)
        self.assertEqual(str(caught.exception), message)

    def test_non_finite_named(self):
        self.assertRefused((math.nan, -119.5, 1000.0), "grid_cell: lat is not finite")
        self.assertRefused((34.0, math.inf, 1000.0), "grid_cell: lon is not finite")
        self.assertRefused((34.0, -math.inf, 1000.0), "grid_cell: lon is not finite")
        self.assertRefused((34.0, -119.5, math.nan), "grid_cell: resolution_m is not finite")
        self.assertRefused((34.0, -119.5, math.inf), "grid_cell: resolution_m is not finite")

    def test_not_a_number_named(self):
        self.assertRefused((True, -119.5, 1000.0), "grid_cell: lat is not a number")
        self.assertRefused((34.0, "120", 1000.0), "grid_cell: lon is not a number")
        self.assertRefused((34.0, -119.5, None), "grid_cell: resolution_m is not a number")
        self.assertRefused((34.0, -119.5, False), "grid_cell: resolution_m is not a number")

    def test_out_of_range_named(self):
        self.assertRefused((91.0, -119.5, 1000.0), "grid_cell: lat outside -90..90")
        self.assertRefused((-90.5, -119.5, 1000.0), "grid_cell: lat outside -90..90")
        self.assertRefused((34.0, 181.0, 1000.0), "grid_cell: lon outside -180..180")
        self.assertRefused((34.0, -180.01, 1000.0), "grid_cell: lon outside -180..180")
        self.assertRefused((91, 181, 1000), "grid_cell: lat outside -90..90")

    def test_non_positive_resolution(self):
        self.assertRefused((34.0, -119.5, 0), "grid_cell: resolution_m must be > 0")
        self.assertRefused((34.0, -119.5, 0.0), "grid_cell: resolution_m must be > 0")
        self.assertRefused((34.0, -119.5, -1000), "grid_cell: resolution_m must be > 0")

    def test_first_bad_argument_is_named(self):
        self.assertRefused((math.nan, "x", 0), "grid_cell: lat is not finite")
        self.assertRefused((34.0, None, math.nan), "grid_cell: lon is not a number")


class Accepted(unittest.TestCase):
    def test_inclusive_bounds_as_on_main(self):
        for lat, lon, ref_lon in ((90.0, 0.0, 0.0), (-90.0, 0.0, 0.0), (0.0, 180.0, -180.0), (0.0, -180.0, -180.0)):
            with self.subTest(lat=lat, lon=lon):
                self.assertEqual(grid_cell(lat, lon, 1000.0), main_formula(lat, ref_lon, 1000.0))

    def test_small_and_integer_resolution(self):
        self.assertEqual(grid_cell(34.0, -119.5, 1), main_formula(34.0, -119.5, 1))
        self.assertEqual(grid_cell(34.0, -119.5, 3000), main_formula(34.0, -119.5, 3000))
        self.assertTrue(grid_cell(34.0, -119.5, 3000)[0].startswith("g3000:"))

    def test_californian_points_byte_identical(self):
        points = ((34.0, -119.5), (32.7157, -117.1611), (35.3659, -120.8499),
                  (36.6002, -121.8947), (37.8044, -122.4783), (41.7558, -124.2026))
        for lat, lon in points:
            for res in (1000.0, 3000.0, 1000, 3000):
                with self.subTest(lat=lat, lon=lon, res=res):
                    got, want = grid_cell(lat, lon, res), main_formula(lat, lon, res)
                    self.assertEqual(got, want)
                    self.assertEqual(repr(got), repr(want))


if __name__ == "__main__":
    unittest.main()

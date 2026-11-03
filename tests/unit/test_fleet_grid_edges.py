"""RF0740-8: ``grid_cell`` gives one cell for the antimeridian and keeps +90 in the top row.

Every other point must give exactly the tuple main's formula gave (cell ids are stored).
Points are synthetic; no AIS data.
"""
import math
import unittest

from skippercast.fleet.ais.aggregate import grid_cell
from skippercast.fleet.ais.simplify import METRES_PER_DEG

POLE_EDGE_M = 11132.0  # 90 / d_lat is a whole number in floating point (asserted below)


def main_formula(lat, lon, resolution_m):
    """grid_cell's arithmetic as on main before RF0740-8 (reference copy)."""
    d_lat = resolution_m / METRES_PER_DEG
    row = math.floor(lat / d_lat)
    centre_lat = (row + 0.5) * d_lat
    d_lon = resolution_m / (METRES_PER_DEG * max(math.cos(math.radians(centre_lat)), 0.01))
    col = math.floor(lon / d_lon)
    centre_lon = (col + 0.5) * d_lon
    return f"g{resolution_m:g}:{row}:{col}", centre_lat, centre_lon


class Antimeridian(unittest.TestCase):
    def test_plus_180_is_minus_180(self):
        for res in (1000.0, 3000.0):
            with self.subTest(res=res):
                east, west = grid_cell(10.0, 180.0, res), grid_cell(10.0, -180.0, res)
                self.assertEqual(east, west)
                self.assertEqual(west, main_formula(10.0, -180.0, res))
                self.assertNotEqual(east, main_formula(10.0, 180.0, res))

    def test_just_west_of_180_keeps_its_column(self):
        for res in (1000.0, 3000.0):
            with self.subTest(res=res):
                got = grid_cell(10.0, 179.999, res)
                self.assertEqual(got, main_formula(10.0, 179.999, res))
                self.assertNotEqual(got[0], grid_cell(10.0, 180.0, res)[0])


class Poles(unittest.TestCase):
    def test_precondition_whole_row_boundary_at_90(self):
        self.assertTrue((90.0 / (POLE_EDGE_M / METRES_PER_DEG)).is_integer())
        self.assertFalse((90.0 / (1000.0 / METRES_PER_DEG)).is_integer())

    def test_north_pole_on_row_boundary_is_top_row(self):
        cell_id, lat, _ = grid_cell(90.0, 0.0, POLE_EDGE_M)
        self.assertLess(lat, 90.0)
        self.assertEqual(cell_id, grid_cell(89.99, 0.0, POLE_EDGE_M)[0])
        self.assertEqual(grid_cell(89.99, 0.0, POLE_EDGE_M), main_formula(89.99, 0.0, POLE_EDGE_M))
        self.assertGreater(main_formula(90.0, 0.0, POLE_EDGE_M)[1], 90.0)  # main drew it off the globe

    def test_north_pole_off_boundary_unchanged(self):
        for res in (1000.0, 3000.0):
            with self.subTest(res=res):
                got = grid_cell(90.0, 0.0, res)
                self.assertEqual(got, main_formula(90.0, 0.0, res))
                self.assertLess(got[1], 90.0)

    def test_south_pole_unchanged(self):
        for res in (1000.0, 3000.0, POLE_EDGE_M):
            with self.subTest(res=res):
                got = grid_cell(-90.0, 0.0, res)
                self.assertEqual(got, main_formula(-90.0, 0.0, res))
                self.assertGreater(got[1], -90.0)


class Regression(unittest.TestCase):
    def test_californian_points_byte_identical(self):
        points = ((34.0, -119.5), (32.7157, -117.1611), (35.3659, -120.8499),
                  (36.6002, -121.8947), (37.8044, -122.4783), (41.7558, -124.2026))
        for lat, lon in points:
            for res in (1000.0, 3000.0):
                with self.subTest(lat=lat, lon=lon, res=res):
                    got, want = grid_cell(lat, lon, res), main_formula(lat, lon, res)
                    self.assertEqual(repr(got), repr(want))


if __name__ == "__main__":
    unittest.main()

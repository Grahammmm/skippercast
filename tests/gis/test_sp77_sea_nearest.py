"""Synthetic producer-shaped grids; no decoder, acquired masks or forecast data."""
import json
import math
import unittest

import numpy as np

from skippercast.forecast import ensemble
from tests._support import FIXTURES

CASES = json.loads((FIXTURES / 'sp77_sea_nearest' / 'cases.json').read_text())


def equatorial_lons(kilometres):
    return np.array([math.degrees(km / 6371.0) for km in kilometres])


def reference_equatorial_distance(longitude):
    # Independent great-circle oracle: arc length along the equator, not the
    # production haversine helper (nor a second call to nearest_sea).
    return abs(math.radians(float(longitude))) * 6371.0


class NearestSeaTests(unittest.TestCase):
    def sample(self, lats, lons, sea, lat=0.0, lon=0.0, **kwargs):
        arrays = (np.array(lats, dtype=float), np.array(lons, dtype=float), np.array(sea, dtype=bool))
        before = [(a.copy(), a.dtype, a.shape, a.tobytes()) for a in arrays]
        result = ensemble.nearest_sea(*arrays, lat, lon, **kwargs)
        for array, (copy, dtype, shape, raw) in zip(arrays, before):
            np.testing.assert_array_equal(array, copy)
            self.assertEqual((array.dtype, array.shape, array.tobytes()), (dtype, shape, raw))
        return result

    def test_primary_round_up_selects_column_zero(self):
        lons = equatorial_lons(CASES['equatorial_km']['round_up'])
        self.assertLess(reference_equatorial_distance(lons[0]), reference_equatorial_distance(lons[1]))
        # Capture product exceptions as data, so only this named semantic
        # assertion can constitute the baseline defect. Import/setup failures
        # occur outside this try and cannot qualify.
        try:
            result = self.sample([0.0], lons, [[True, True]])
            observed = None if result is None else result[1]
        except (TypeError, ValueError, ArithmeticError) as error:
            observed = {'exception': type(error).__name__, 'message': str(error)}
        print('PRIMARY_OBSERVATION=' + json.dumps(observed), flush=True)
        self.assertEqual(observed, 0, 'SP77_PRIMARY_COLUMN_ZERO')

    def test_healthy_mask_control_selects_column_zero(self):
        lons = equatorial_lons(CASES['equatorial_km']['round_up'])
        result = self.sample([0.0], lons, [[True, False]])
        self.assertEqual(result[:2], (0, 0))
        self.assertEqual(result[4], 1.0)

    def test_reversed_round_up_order_selects_later_nearer_cell(self):
        lons = equatorial_lons(list(reversed(CASES['equatorial_km']['round_up'])))
        self.assertLess(reference_equatorial_distance(lons[1]), reference_equatorial_distance(lons[0]))
        self.assertEqual(self.sample([0.0], lons, [[True, True]])[:2], (0, 1))

    def test_round_down_does_not_hide_later_nearer_cell(self):
        lons = equatorial_lons(CASES['equatorial_km']['round_down'])
        self.assertLess(reference_equatorial_distance(lons[1]), reference_equatorial_distance(lons[0]))
        self.assertEqual(self.sample([0.0], lons, [[True, True]])[:2], (0, 1))

    def test_round_down_preserves_first_nearer_cell(self):
        lons = equatorial_lons(list(reversed(CASES['equatorial_km']['round_down'])))
        self.assertLess(reference_equatorial_distance(lons[0]), reference_equatorial_distance(lons[1]))
        self.assertEqual(self.sample([0.0], lons, [[True, True]])[:2], (0, 0))

    def test_equal_distance_retains_first_row_and_column(self):
        # Identical coordinates make exact binary-distance ties, including when
        # presentation rounding would otherwise make a later cell look nearer.
        for km in (0.996, 1.004, 0.0):
            with self.subTest(km=km):
                x = equatorial_lons([km])[0]
                self.assertEqual(self.sample([0.0, 0.0], [x, x], [[True, True], [True, True]])[:2], (0, 0))

    def test_radius_exact_and_adjacent_floats(self):
        x = equatorial_lons([1.0])[0]
        # Exact product metric is intentional here: exercise <= and its adjacent
        # representable bounds without conflating radius comparison with oracle
        # floating-point differences. Ordering tests use the independent oracle.
        distance = ensemble.distance_km(0.0, 0.0, 0.0, float(x))
        self.assertAlmostEqual(distance, reference_equatorial_distance(x), places=12)
        self.assertIsNotNone(self.sample([0.0], [x], [[True]], radius_km=distance))
        self.assertIsNone(self.sample([0.0], [x], [[True]], radius_km=math.nextafter(distance, -math.inf)))
        self.assertIsNotNone(self.sample([0.0], [x], [[True]], radius_km=math.nextafter(distance, math.inf)))
        self.assertEqual(self.sample([0.0], [0.0], [[True]], radius_km=0.0), (0, 0, 0.0, 0.0, 0.0))

    def test_land_cannot_win_even_when_closest(self):
        lons = equatorial_lons([0.0, 2.0])
        self.assertEqual(self.sample([0.0], lons, [[False, True]])[:2], (0, 1))

    def test_empty_axes_return_none(self):
        for lats, lons, sea in (([], [], np.zeros((0, 0))), ([], [0], np.zeros((0, 1))),
                                ([0], [], np.zeros((1, 0)))):
            with self.subTest(shape=sea.shape):
                self.assertIsNone(self.sample(lats, lons, sea))

    def test_all_land_returns_none(self):
        self.assertIsNone(self.sample([0.0], [0.0, 0.1], [[False, False]]))

    def test_outside_radius_and_window_return_none(self):
        self.assertIsNone(self.sample([0.0], equatorial_lons([31.0]), [[True]]))
        self.assertIsNone(self.sample([5.0], [5.0], [[True]]))

    def test_presentation_tuple_and_ordinary_selection_unchanged(self):
        lat = CASES['presentation']['latitude']
        lon = CASES['presentation']['longitude']
        self.assertEqual(self.sample([lat], [lon], [[True]], lat, lon),
                         (0, 0, 35.12346, -121.98765, 0.0))
        result = self.sample([0.0], equatorial_lons(CASES['equatorial_km']['ordinary']), [[True, True, True]])
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 5)
        self.assertEqual(result, (0, 1, 0.0, round(float(equatorial_lons([2.0])[0]), 5), 2.0))
        self.assertIs(type(result[0]), int)
        self.assertIs(type(result[1]), int)

    def test_wrapped_longitudes_keep_existing_selection(self):
        self.assertEqual(self.sample([0.0], [359.999, 359.99], [[True, True]])[:2], (0, 0))


if __name__ == '__main__':
    unittest.main()

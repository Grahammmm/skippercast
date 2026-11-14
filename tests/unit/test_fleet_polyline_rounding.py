"""encode_polyline rounds the scaled binary float like JavaScript Math.round."""

import math
import unittest

from skippercast.fleet.ais.simplify import decode_polyline, encode_polyline, simplify_encode

BELOW = math.nextafter(0.000005, -math.inf)
ABOVE = math.nextafter(0.000005, math.inf)
NEG_BELOW = math.nextafter(-0.000005, math.inf)  # closer to zero
NEG_ABOVE = math.nextafter(-0.000005, -math.inf)  # further from zero


def js_round(scaled: float) -> int:
    """Exact ties-toward-+infinity rounding from the float's integer ratio."""
    n, d = scaled.as_integer_ratio()
    return (2 * n + d) // (2 * d)


def cells(points):
    return [(round(a * 1e5), round(b * 1e5)) for a, b in decode_polyline(encode_polyline(points))]


class PolylineRoundingTests(unittest.TestCase):
    def test_below_positive_half_stays_lower(self):
        self.assertLess(BELOW * 1e5, 0.5)
        self.assertEqual(encode_polyline([(BELOW, 0.0)]), "??")
        self.assertEqual(decode_polyline("??"), [(0.0, 0.0)])
        self.assertEqual(simplify_encode([(BELOW, 0.0)], 10.0), "??")

    def test_longitude_rounds_independently(self):
        self.assertEqual(encode_polyline([(0.0, BELOW)]), "??")
        self.assertEqual(simplify_encode([(0.0, BELOW)], 10.0), "??")

    def test_positive_tie_and_successor_round_up(self):
        self.assertEqual(encode_polyline([(0.000005, 0.0)]), "A?")
        self.assertEqual(encode_polyline([(ABOVE, 0.0)]), "A?")
        self.assertEqual(decode_polyline("A?"), [(0.00001, 0.0)])

    def test_negative_neighbors_keep_js_direction(self):
        self.assertEqual(encode_polyline([(NEG_ABOVE, 0.0)]), "@?")
        self.assertEqual(encode_polyline([(-0.000005, 0.0)]), "??")
        self.assertEqual(encode_polyline([(NEG_BELOW, 0.0)]), "??")
        self.assertEqual(encode_polyline([(-0.0, -0.0)]), "??")

    def test_integer_ratio_oracle(self):
        for v in (BELOW, 0.000005, ABOVE, NEG_ABOVE, -0.000005, NEG_BELOW, 1.0000049999999998, -1.5e-5):
            with self.subTest(v=v):
                self.assertEqual(cells([(v, 0.0)]), [(js_round(v * 1e5), 0)])

    def test_absolute_rounding_then_deltas(self):
        pts = [(BELOW, 0.000005), (0.000005, BELOW), (BELOW, 0.000005)]
        expected = [(0, 1), (1, 0), (0, 1)]
        self.assertEqual(cells(pts), expected)
        self.assertEqual(cells(iter(pts)), expected)
        self.assertEqual(encode_polyline(iter(pts)), encode_polyline(pts))
        self.assertEqual(encode_polyline(pts), "?AA@@A")

    def test_goldens_and_inputs_unchanged(self):
        pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        self.assertEqual(encode_polyline(pts), "_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        copy = list(pts)
        simplify_encode(pts, 1.0)
        self.assertEqual(pts, copy)
        self.assertIsNone(simplify_encode([], 1.0))


if __name__ == "__main__":
    unittest.main()

"""RF0720-6: fleet AIS simplify/encode_polyline refuse non-real positions by point index."""
from __future__ import annotations

import math
import unittest

from skippercast.fleet.ais.simplify import encode_polyline, simplify, simplify_encode

GOLDEN = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
GOLDEN_ENCODED = '_p~iF~ps|U_ulLnnqC_mqNvxq`@'
NAN, INF = float('nan'), float('inf')


def _track(bad, at=2, n=5):
    points = [(10.0 + k * 0.01, -150.0 + (k % 2) * 0.01) for k in range(n)]
    points[at] = bad
    return points


class SimplifyPointTest(unittest.TestCase):
    def refused(self, points, message, tolerance=25):
        with self.assertRaises(ValueError) as caught:
            simplify(points, tolerance)
        self.assertEqual(str(caught.exception), message)

    def test_nan_middle_point_is_refused_not_collapsed(self):
        self.refused(_track((NAN, -150.0)), 'point 2: not finite')
        self.refused(_track((10.02, NAN)), 'point 2: not finite')
        self.refused(_track((INF, -150.0)), 'point 2: not finite')
        self.refused(_track((10.02, -INF)), 'point 2: not finite')

    def test_ais_not_available_sentinels_are_refused(self):
        self.refused(_track((91.0, 181.0), at=0), 'point 0: latitude outside -90..90')
        self.refused(_track((35.0, 181.0), at=0), 'point 0: longitude outside -180..180')
        self.refused(_track((-90.5, 0.0), at=4), 'point 4: latitude outside -90..90')
        self.refused(_track((35.0, -180.5), at=3), 'point 3: longitude outside -180..180')
        self.refused(_track((91, 120), at=1), 'point 1: latitude outside -90..90')

    def test_inclusive_bounds_are_accepted(self):
        points = [(90.0, -180.0), (-90.0, 180.0)]
        self.assertEqual(simplify(points, 25), points)
        self.assertEqual(simplify(points[:1], 0), points[:1])
        self.assertIsInstance(encode_polyline(points), str)

    def test_shape_and_number_messages(self):
        cases = [
            ((True, 120.0), 'point 2: latitude is not a number'),
            ((35.0, False), 'point 2: longitude is not a number'),
            (('35', 120.0), 'point 2: latitude is not a number'),
            ((35.0, None), 'point 2: longitude is not a number'),
            ((35.0,), 'point 2: not a (lat, lon) pair'),
            ([35.0, 120.0, 0], 'point 2: not a (lat, lon) pair'),
            (None, 'point 2: not a (lat, lon) pair'),
            ('35,120', 'point 2: not a (lat, lon) pair'),
            ({'lat': 35.0, 'lon': 120.0}, 'point 2: not a (lat, lon) pair'),
        ]
        for bad, message in cases:
            with self.subTest(bad=bad):
                self.refused(_track(bad), message)
        # A list pair is still a pair; a non-number wins over a NaN in the other slot.
        self.assertEqual(simplify([[10.0, -150.0], (10.1, -150.0)], 25), [[10.0, -150.0], (10.1, -150.0)])
        self.refused(_track((NAN, 'x')), 'point 2: longitude is not a number')

    def test_short_lists_are_checked_too(self):
        self.refused([(10.0, -150.0), (NAN, -150.0)], 'point 1: not finite')
        self.refused([(91.0, 0.0)], 'point 0: latitude outside -90..90')
        self.refused([None], 'point 0: not a (lat, lon) pair')
        self.assertEqual(simplify([], 25), [])
        with self.assertRaises(ValueError):
            simplify_encode([(NAN, 0.0)], 25)

    def test_tolerance_must_be_a_real_number(self):
        for bad in (True, False, '5', -1, -0.5, INF, NAN, None):
            with self.subTest(tolerance=bad):
                self.refused(GOLDEN, 'tolerance_m must be a finite number >= 0', tolerance=bad)
        self.assertEqual(simplify(GOLDEN, 0), GOLDEN)
        self.assertEqual(simplify(GOLDEN, 5), GOLDEN)
        self.assertEqual(simplify(GOLDEN, 0.0), GOLDEN)

    def test_tolerance_checked_before_points(self):
        self.refused([None], 'tolerance_m must be a finite number >= 0', tolerance=True)


class EncodePointTest(unittest.TestCase):
    def refused(self, points, message):
        with self.assertRaises(ValueError) as caught:
            encode_polyline(points)
        self.assertEqual(str(caught.exception), message)

    def test_non_finite_keeps_existing_message(self):
        self.refused([(NAN, 0)], 'polyline points must be finite')
        self.refused([(0.0, INF)], 'polyline points must be finite')
        self.refused(iter([(1.0, 2.0), (-INF, 0.0)]), 'polyline points must be finite')

    def test_out_of_range_and_non_numbers_named_by_index(self):
        self.refused([(95, 0)], 'point 0: latitude outside -90..90')
        self.refused([(1.0, 2.0), (35.0, 181.0)], 'point 1: longitude outside -180..180')
        self.refused([(1.0, 2.0), (True, 2.0)], 'point 1: latitude is not a number')
        self.refused([(1.0, 2.0), (1.0, '2')], 'point 1: longitude is not a number')
        self.refused([(1.0, 2.0), (1.0, 2.0, 3.0)], 'point 1: not a (lat, lon) pair')
        self.refused([None], 'point 0: not a (lat, lon) pair')


class GoldenUnchangedTest(unittest.TestCase):
    def test_golden_track_simplifies_and_encodes_identically(self):
        self.assertEqual(simplify(GOLDEN, 25), GOLDEN)
        self.assertEqual(encode_polyline(GOLDEN), GOLDEN_ENCODED)
        self.assertEqual(encode_polyline(simplify(GOLDEN, 25)), GOLDEN_ENCODED)
        self.assertEqual(simplify_encode(GOLDEN, 25), GOLDEN_ENCODED)
        self.assertEqual(encode_polyline([(38, -120), (40.7, -120.95)]), encode_polyline([(38.0, -120.0), (40.7, -120.95)]))
        self.assertTrue(all(math.isfinite(v) for p in simplify(GOLDEN, 25) for v in p))


if __name__ == '__main__':
    unittest.main()

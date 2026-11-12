"""Simplification keeps real backtracks across the antimeridian (RF0211-8). Synthetic tracks only."""

from __future__ import annotations

from types import SimpleNamespace
import math
import unittest

from skippercast.fleet.ais.classify import Segment
from skippercast.fleet.ais.events import segment_geometry
from skippercast.fleet.ais.simplify import METRES_PER_DEG, decode_polyline, simplify, simplify_encode

TOL = 25.0


def local_x_m(lons: list[float]) -> list[float]:
    """Independent continuous east offsets (equator): each step is the shortest arc."""
    out, x = [0.0], 0.0
    for a, b in zip(lons, lons[1:]):
        d = (b - a + 180.0) % 360.0 - 180.0
        x += d * METRES_PER_DEG
        out.append(x)
    return out


class SeamBacktrackTests(unittest.TestCase):
    def test_eastward_seam_backtrack_exceeds_tolerance(self):
        track = [(0, 179.9), (0, 179.8), (0, -179.9)]
        x = local_x_m([p[1] for p in track])
        self.assertGreater(abs(x[1] - x[0]) , 10000)  # 0.1 deg back, independent of the module
        self.assertGreater(min(abs(x[1] - x[0]), abs(x[1] - x[2])), TOL)
        self.assertEqual(simplify(track, TOL), track)
        self.assertEqual(decode_polyline(simplify_encode(track, TOL)), [(0.0, 179.9), (0.0, 179.8), (0.0, -179.9)])

    def test_westward_seam_backtrack_exceeds_tolerance(self):
        track = [(0, -179.9), (0, -179.8), (0, 179.9)]
        self.assertEqual(simplify(track, TOL), track)
        self.assertEqual(decode_polyline(simplify_encode(track, TOL)), [(0.0, -179.9), (0.0, -179.8), (0.0, 179.9)])

    def test_straight_short_seam_track_collapses(self):
        track = [(0, 179.9), (0, 180), (0, -179.9)]
        self.assertEqual(simplify(track, TOL), [track[0], track[2]])
        spelled = [(0, 179.9), (0, -180), (0, -179.9)]
        self.assertEqual(simplify(spelled, TOL), [spelled[0], spelled[2]])
        longer = [(0, 179.8), (0, 179.9), (0, 180), (0, -179.9), (0, -179.8)]
        self.assertEqual(simplify(longer, TOL), [longer[0], longer[-1]])

    def test_multiple_crossings_keep_local_excursions(self):
        track = [[0, 179.9], [0.1, -179.95], [0, 179.95], [0.1, -179.85], [0, -179.8]]
        before = [list(p) for p in track]
        # independent continuous local track (equator-ish, degrees): y is latitude
        x = local_x_m([p[1] for p in track])
        y = [p[0] * METRES_PER_DEG for p in track]
        # points 1 and 3 are ~11 km off the y == 0 start-to-end line, so both turns survive; once
        # split at point 1, point 2 (y == 0) is ~11 km from the chord 1 -> 4 as well
        self.assertGreater(y[1], TOL)
        self.assertGreater(y[3], TOL)
        self.assertTrue(x[0] < x[2] < x[4])
        kept = simplify(track, TOL)
        self.assertEqual(len(kept), len(track))
        self.assertTrue(all(a is b for a, b in zip(kept, track)))
        self.assertEqual(track, before)

    def test_nonseam_and_exact_half_turn_compatibility(self):
        ordinary = [(0, -0.1), (0, -0.2), (0, 0.1)]
        self.assertEqual(simplify(ordinary, TOL), ordinary)
        corner = [(0, 10.0), (0.1, 10.0), (0.1, 10.1)]
        self.assertEqual(simplify(corner, TOL), corner)
        self.assertEqual(simplify(corner, 0), corner)
        self.assertEqual(simplify([(0, 0.0), (0.0001, 0.00002), (0, 0.0002)], 0), [(0, 0.0), (0.0001, 0.00002), (0, 0.0002)])
        # google reference vector stays the same
        ref = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        self.assertEqual(simplify_encode(ref, 0), "_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        # exact +-180 deltas keep their signed spelling and do not raise
        for track in ([(0, 0), (0, 180), (0, 0)], [(0, 0), (0, -180), (0, 0)], [(0, -180), (0, 180), (0, -180)]):
            self.assertEqual(len(simplify(track, TOL)) in (2, 3), True)

    def test_real_segment_geometry_preserves_turn(self):
        def fixes(*lons):
            return tuple(SimpleNamespace(lat=0.0, lon=lon) for lon in lons)

        fishing = Segment(0, 'fishing', 0, 1, fixes(179.9, 179.8, -179.9), 1.0, 0.5, 0.1)
        uncertain = Segment(1, 'uncertain', 0, 1, fixes(-179.9, -179.8, 179.9), 1.0, 0.5, 0.1)
        self.assertEqual(decode_polyline(segment_geometry(fishing, TOL)), [(0.0, 179.9), (0.0, 179.8), (0.0, -179.9)])
        self.assertEqual(decode_polyline(segment_geometry(uncertain, TOL)), [(0.0, -179.9), (0.0, -179.8), (0.0, 179.9)])
        self.assertIsNone(segment_geometry(Segment(2, 'transit', 0, 1, fixes(179.9, 179.8, -179.9), 6.0, 1.0, 0.0), TOL))
        self.assertIsNone(segment_geometry(Segment(3, 'gap', 0, 1, (), None, None, None), TOL))

    def test_existing_input_validation_remains(self):
        with self.assertRaises(ValueError):
            simplify([(0, 181), (0, 0), (0, 1)], TOL)
        with self.assertRaises(ValueError):
            simplify([(0, 1), (0, 2), (0, 3)], -1)
        self.assertEqual(simplify([(0, 179.9)], TOL), [(0, 179.9)])
        self.assertTrue(math.isfinite(METRES_PER_DEG))


if __name__ == '__main__':
    unittest.main()

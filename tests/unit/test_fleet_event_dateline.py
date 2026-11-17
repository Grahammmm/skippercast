"""Compact dateline fishing events keep a local centre and radius (RF1210-8). Synthetic fixes only."""
import itertools
import unittest

from skippercast.fleet.ais.classify import Classification, Segment
from skippercast.fleet.ais.events import build_events, median_point, p90_radius_m
from tests.unit.test_fleet_classify import MIN, PORTS, T0
from tests.unit.test_fleet_events import ctx, fix


def one_event(lons_lats, kind='drift-anchor'):
    positions = tuple(fix(T0 + i * MIN, lat, lon) for i, (lat, lon) in enumerate(lons_lats))
    segment = Segment(0, kind, T0, T0 + 30 * MIN, positions, 0.5, 0.2, 0.1)
    return build_events(Classification(None, (segment,), 'c1-x'), PORTS, ctx())


class DatelineMedianTest(unittest.TestCase):
    def test_two_fix_seam_cluster_stays_local(self):
        pts = [(10.0, 179.999), (10.0, -179.999)]
        self.assertEqual(median_point(pts), (10.0, -180.0))
        [e] = one_event(pts)
        self.assertEqual((e.lat, e.lon), (10.0, -180.0))
        self.assertLess(e.radius_m, 200)
        self.assertLessEqual(p90_radius_m(pts, (e.lat, e.lon)), e.radius_m + 0.1)

    def test_asymmetric_clusters_and_order_independence(self):
        pts = [(10.0, 179.9), (10.2, 179.95), (10.1, -179.99), (10.3, 179.8), (10.4, -179.9)]
        # unwrapped: 179.8, 179.9, 179.95, 180.01, 180.1 -> median 179.95
        original = list(pts)
        self.assertEqual(median_point(pts), (10.2, 179.95))
        self.assertEqual(pts, original)
        for perm in itertools.permutations(pts):
            self.assertEqual(median_point(perm), (10.2, 179.95))
        even = [(0.0, 179.0), (0.0, 179.5), (0.0, -179.5), (0.0, -179.0)]
        # unwrapped 179, 179.5, 180.5, 181 -> median 180 -> -180
        self.assertEqual(median_point(even), (0.0, -180.0))
        self.assertEqual(median_point(even[::-1]), (0.0, -180.0))
        west = [(0.0, 179.0), (0.0, -179.0), (0.0, -179.5)]
        self.assertEqual(median_point(west), (0.0, -179.5))

    def test_endpoints_and_duplicates(self):
        [e] = one_event([(5.0, 180.0), (5.0, -180.0), (5.0, 180.0)])
        self.assertEqual((e.lat, e.lon, e.radius_m), (5.0, -180.0, 0.0))
        self.assertEqual(median_point([(1.0, 180.0)]), (1.0, 180.0))
        self.assertEqual(median_point([(1.0, -180.0)]), (1.0, -180.0))
        same = median_point([(2.0, 7.5)] * 3)
        self.assertEqual(same, (2.0, 7.5))

    def test_nonseam_and_ambiguous_compatibility(self):
        self.assertEqual(median_point([(1.0, -150.0), (3.0, -149.0)]), (2.0, -149.5))
        self.assertEqual(median_point([(1.0, 100.0), (3.0, 101.0)]), (2.0, 100.5))
        self.assertEqual(median_point([(0.0, -0.5), (0.0, 0.5)]), (0.0, 0.0))
        self.assertEqual(median_point([(0.0, -90.0), (0.0, 90.0)]), (0.0, 0.0))  # span exactly 180
        # raw span > 180, but unwrapped span is also >= 180: old median kept
        self.assertEqual(median_point([(0.0, -170.0), (0.0, 20.0), (0.0, 10.0)]), (0.0, 10.0))
        self.assertEqual(median_point([(0.0, 170.0), (0.0, -20.0), (0.0, 10.0)]), (0.0, 10.0))
        with self.assertRaises(ValueError):
            median_point([])

    def test_event_envelope_and_harbor_exclusion(self):
        pts = [(10.0, 179.999), (10.0, -179.999)]
        [e] = one_event(pts)
        [plain] = one_event([(20.0, -150.0), (20.0, -149.998)])
        for field in ('kind', 'region', 'source', 'rights', 'classifier_version', 'dwell_min'):
            self.assertEqual(getattr(e, field), getattr(plain, field))
        self.assertEqual(e.kind, 'drift-anchor')
        self.assertEqual(e.ended_at - e.started_at, 30 * MIN)
        # harbor fixes are ignored: PORTS geofences sit in open ocean, so a fix inside one must not move the centre
        harbor_lat, harbor_lon = 10.0, -150.0
        [h] = one_event(pts + [(harbor_lat, harbor_lon)])
        self.assertEqual((h.lat, h.lon, h.radius_m), (e.lat, e.lon, e.radius_m))
        self.assertEqual(one_event([(harbor_lat, harbor_lon)]), [])
        self.assertEqual(one_event(pts, kind='transit'), [])


if __name__ == '__main__':
    unittest.main()

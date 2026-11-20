"""Polar WGS84 latitudes project to the finite Web Mercator world edge."""
import copy
import math
import unittest
import xml.etree.ElementTree as ET

from skippercast.platform.startup_forms import mercator, poster_svg

LIMIT = math.degrees(math.atan(math.sinh(math.pi)))


def _reference_y(latitude, zoom=0):
    phi = math.radians(latitude)
    return (0.5 - math.log(math.tan(math.pi / 4 + phi / 2)) / (2 * math.pi)) * 512 * 2 ** zoom


class PolarMercatorTests(unittest.TestCase):
    def test_poles_project_to_finite_world_edges(self):
        x, north = mercator(0, 90, 0)
        self.assertEqual(x, 256)
        self.assertAlmostEqual(north, 0, places=6)
        self.assertAlmostEqual(mercator(0, -90, 0)[1], 512, places=6)

    def test_latitudes_beyond_mercator_limit_saturate(self):
        for sign in (1, -1):
            edge = mercator(0, sign * LIMIT, 0)
            for latitude in (86, 89, 90):
                self.assertEqual(mercator(0, sign * latitude, 0), edge)
        self.assertLess(abs(mercator(0, LIMIT - 0.01, 0)[1] - mercator(0, LIMIT, 0)[1]), 0.5)

    def test_nonpolar_projection_and_zoom_controls(self):
        self.assertEqual(mercator(0, 0, 0), (256, 256))
        for latitude in (45, -30, 80):
            self.assertAlmostEqual(mercator(10, latitude, 0)[1], _reference_y(latitude), places=9)
            self.assertAlmostEqual(mercator(10, latitude, 3)[1], _reference_y(latitude, 3), places=7)
        self.assertAlmostEqual(mercator(90, 0, 2)[0], (270 / 360) * 2048)

    def test_polar_overview_makes_parseable_finite_svg(self):
        overview = {'provenance': {'bounds': [-10, 80, 10, 90]},
                    'features': [{'geometry': {'coordinates': [[[-10, 80], [0, 90], [10, 85]]]}}]}
        before = copy.deepcopy(overview)
        svg = poster_svg(overview, {'sha256': 'a' * 64})
        root = ET.fromstring(svg)
        self.assertEqual(overview, before)
        self.assertEqual(root.get('data-sha256'), 'a' * 64)
        for token in str(root.get('viewBox')).split():
            self.assertTrue(math.isfinite(float(token)))
        self.assertNotIn('nan', svg.lower())
        self.assertNotIn('inf', svg.lower())
        self.assertTrue(str(root[1].get('d')).startswith('M'))


if __name__ == '__main__':
    unittest.main()

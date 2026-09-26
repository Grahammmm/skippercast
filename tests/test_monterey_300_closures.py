import unittest

from shapely.geometry import box

from scripts.audit_monterey_300_closures import official_query_envelope, screen_geometry


class FullFootprintClosureTests(unittest.TestCase):
    def test_edge_is_held_even_when_centroid_is_farther_away(self):
        footprint = box(0, 0, 100, 100)
        mpa = box(190, 0, 300, 100)
        gea = box(1000, 1000, 1100, 1100)
        result = screen_geometry(footprint, mpa, gea)
        self.assertEqual(result["nearest_cdfw_mpa_m"], 90)
        self.assertTrue(result["within_100m_closure_review_buffer"])

    def test_clear_geometry_still_returns_distance_only(self):
        result = screen_geometry(box(0, 0, 100, 100), box(301, 0, 400, 100),
                                 box(1000, 1000, 1100, 1100))
        self.assertFalse(result["within_100m_closure_review_buffer"])

    def test_official_query_coverage_is_explicit(self):
        url = ("https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/"
               "biosds582_fpu/FeatureServer/0/query?geometry=-122.5%2C36.4%2C-121.5%2C36.9"
               "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects")
        self.assertTrue(official_query_envelope(url).covers(box(-122, 36.5, -121.8, 36.7)))
        with self.assertRaises(ValueError):
            official_query_envelope(url.replace("inSR=4326", "inSR=3857"))


if __name__ == "__main__":
    unittest.main()

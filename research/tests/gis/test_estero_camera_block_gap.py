import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping

from research.scripts.audit_estero_camera_block_gap import inspect


class EsteroCameraBlockGapTests(unittest.TestCase):
    def setUp(self):
        lon, lat = -120.8, 35.3
        x, y = Transformer.from_crs(4326, 32610, always_xy=True).transform(lon, lat)
        self.position = (lon, lat)
        self.blocks = {
            "scope": "private-estero-nominal-research-blocks", "crs": "EPSG:32610",
            "features": [{"geometry": mapping(box(x + 500 + i * 200, y, x + 600 + i * 200, y + 100))}
                         for i in range(60)],
        }

    def test_missing_camera_support_does_not_create_target(self):
        result = inspect(self.blocks, [(self.position[0], self.position[1],
                                        {"MAJOR_GEO": "rock", "rockfish": 1})])
        self.assertAlmostEqual(result["nearest_camera_to_any_block_m"], 500, delta=.2)
        self.assertEqual(result["distance_counts"]["within_250m"]["all"], 0)

    def test_close_camera_is_counted_at_supported_radius(self):
        lon, lat = self.position
        x, y = Transformer.from_crs(4326, 32610, always_xy=True).transform(lon, lat)
        self.blocks["features"][0]["geometry"] = mapping(box(x + 50, y, x + 150, y + 100))
        result = inspect(self.blocks, [(lon, lat, {"MAJOR_GEO": "rock", "rockfish": 1})])
        self.assertEqual(result["distance_counts"]["within_0m"]["all"], 0)
        self.assertEqual(result["distance_counts"]["within_100m"]["rock_boulder_cobble"], 1)
        self.assertEqual(result["distance_counts"]["within_100m"]["rockfish_positive"], 1)

    def test_changed_block_index_fails(self):
        self.blocks["features"].pop()
        with self.assertRaises(ValueError):
            inspect(self.blocks, [(self.position[0], self.position[1], {})])


if __name__ == "__main__":
    unittest.main()

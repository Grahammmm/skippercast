import unittest

from pyproj import Transformer
from shapely.geometry import Point

from scripts.audit_nos_seabed_samples import audit


class NosSeabedGapAuditTest(unittest.TestCase):
    def test_nearby_historic_sample_does_not_become_fishing_target(self):
        project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
        center = Point(*project.transform(-120.9, 35.3))
        point = Point(center.x + 140, center.y)
        back = Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True)
        lon, lat = back.transform(point.x, point.y)
        features = [{"geometry": {"x": lon, "y": lat}, "attributes": {
            "BEGIN_OBSTIM": 765331200000, "SURVEY": "H10531", "SOURCE": "NMNH",
            "DESCRP": "MUD,GRN"}}]
        result = audit(features, {"test": [center.buffer(100)]})
        row = result["area_summary"]["test"]
        self.assertEqual(row["samples_inside"], 0)
        self.assertEqual(row["samples_within_100m"], 1)
        self.assertAlmostEqual(row["nearest_sample_m"], 40, places=1)
        self.assertFalse(result["fishing_target"])
        self.assertFalse(result["exportable"])

    def test_missing_geometry_is_not_zero_distance(self):
        with self.assertRaises(ValueError):
            audit([{"geometry": {}, "attributes": {}}], {"test": []})


if __name__ == "__main__":
    unittest.main()

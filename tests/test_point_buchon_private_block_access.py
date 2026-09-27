import copy
import unittest

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform

from scripts.audit_point_buchon_private_block_access import audit


class PointBuchonPrivateBlockAccessTest(unittest.TestCase):
    def setUp(self):
        inverse = Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True).transform
        center = 690000, 3900000
        block = box(center[0], center[1], center[0] + 100, center[1] + 100)
        far = box(center[0] + 5000, center[1], center[0] + 5100, center[1] + 100)
        # Only one block intersects the protected polygon and a charted feature.
        geom = lambda g: {"type": "Feature", "geometry": mapping(g), "properties": {}}
        mpa = lambda name, g: {"type": "Feature", "geometry": mapping(transform(inverse, g)),
                               "properties": {"NAME": name}}
        hazard = geom(transform(inverse, box(center[0] + 50, center[1] + 50,
                                             center[0] + 52, center[1] + 52)))
        self.inputs = {
            "rov_blocks": {"crs": "EPSG:32610", "features": [geom(block)] + [geom(far)] * 25},
            "terrain_blocks": {"crs": "EPSG:32610", "features": [geom(far)] * 181},
            "cdfw_mpas": {"crs": {"properties": {"name": "EPSG:4326"}},
                          "checked_at": "2026-09-26T00:00:00Z", "source_url": "https://example.test/mpa",
                          "features": [mpa("Point Buchon SMCA", block),
                                       mpa("Point Buchon SMR", box(710000, 3900000, 710100, 3900100)),
                                       mpa("Morro Bay SMRMA", box(720000, 3900000, 720100, 3900100))]},
            "noaa_enc": {"scope_id": "point-buchon-open-reference-hard-context",
                         "bounds": [-123, 34, -120, 36],
                         "query_receipts": [{"count": 1}] + [{"count": 0}] * 17,
                         "checked_at": "2026-09-26T00:00:00Z", "source_url": "https://example.test/enc",
                         "features": [hazard]},
        }

    def test_proximity_is_research_only(self):
        result = audit(self.inputs)
        self.assertEqual(result["groups"]["rov_blocks"]["any_mpa_intersection"], 1)
        self.assertEqual(result["groups"]["rov_blocks"]["any_enc_feature_within_100m"], 1)
        self.assertEqual(result["groups"]["terrain_blocks"]["any_enc_feature_within_250m"], 0)
        self.assertFalse(result["full_footprint_legal_chart_access_verified"])
        self.assertFalse(result["exportable"])
        self.assertNotIn("features", result)

    def test_changed_scope_fails_closed(self):
        changed = copy.deepcopy(self.inputs)
        changed["noaa_enc"]["query_receipts"] = changed["noaa_enc"]["query_receipts"][:-1]
        with self.assertRaises(ValueError):
            audit(changed)

    def test_incomplete_query_footprint_fails_closed(self):
        changed = copy.deepcopy(self.inputs)
        changed["noaa_enc"]["bounds"] = [-123, 34, -122, 36]
        with self.assertRaisesRegex(ValueError, "does not cover"):
            audit(changed)


if __name__ == "__main__":
    unittest.main()

"""The central coast context layer must never become a fishing/export layer."""
import json
import unittest
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union


ROOT = Path(__file__).resolve().parents[1]
REGIONS = (
    "santa-cruz-monterey-bay", "monterey-point-sur", "big-sur-coast",
    "south-big-sur-san-simeon", "cambria-san-simeon",
)
TO_METERS = Transformer.from_crs(4326, 32610, always_xy=True).transform


class CentralHabitatContext(unittest.TestCase):
    def test_region_layers_are_research_only_and_clear_mpas(self):
        for region_id in REGIONS:
            with self.subTest(region=region_id):
                config = json.loads((ROOT / "regions" / region_id / "region.json").read_text())
                layer = json.loads((ROOT / "dist" / config["assets"]["survey_habitat"]).read_text())
                protected = json.loads((ROOT / "dist" / config["assets"]["protected_areas"]).read_text())
                closure = unary_union([transform(TO_METERS, shape(f["geometry"])) for f in protected["features"]])
                bounds = box(*config["fishing_bounds"]).buffer(1e-8)
                self.assertEqual(layer["region_id"], region_id)
                self.assertEqual(layer["fishing_targets"], 0)
                self.assertGreater(len(layer["features"]), 0)
                for feature in layer["features"]:
                    properties = feature["properties"]
                    geometry = shape(feature["geometry"])
                    self.assertTrue(geometry.is_valid)
                    self.assertTrue(bounds.covers(geometry))
                    self.assertGreaterEqual(transform(TO_METERS, geometry).distance(closure), 100)
                    self.assertIs(properties["fishing_target"], False)
                    self.assertIs(properties["fishing_export"], False)
                    self.assertIs(properties["depth_qualified"], False)
                    self.assertIsNone(properties["quality_grade"])


if __name__ == "__main__":
    unittest.main()

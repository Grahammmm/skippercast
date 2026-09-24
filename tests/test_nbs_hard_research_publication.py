"""Guard the distinction between measured seabed research and fishing targets."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NbsHardResearchPublicationTests(unittest.TestCase):
    def test_estero_layer_contains_only_screened_research_outlines(self):
        review = json.loads((ROOT / "dist/data/nbs-central-usgs-hard-overlap-review.json").read_text())
        layer = json.loads((ROOT / "dist/data/central-nbs-usgs-hard-research-context.geojson").read_text())
        self.assertEqual(review["status"], "research-leads-only")
        self.assertFalse(review["fishing_target"])
        self.assertFalse(review["exportable"])
        self.assertEqual(layer["scope"], "central-nbs-usgs-hard-research-context")
        self.assertEqual(layer["coast_id"], "central")
        self.assertLessEqual(len(layer["features"]), layer["maximum_displayed_per_tile"])
        self.assertEqual(len({f["properties"]["id"] for f in layer["features"]}),
                         len(layer["features"]))
        source_tiles = {tile["tile"]: tile for sector in review["sectors"] for tile in sector["tiles"]}
        for feature in layer["features"]:
            p = feature["properties"]
            self.assertEqual(p["sector_id"], "cambria-morro")
            self.assertTrue(all(p[key] is False for key in (
                "fishing_target", "exportable", "legal_clearance", "fish_confirmed",
                "depth_qualified_for_target")))
            self.assertGreaterEqual(p["approx_display_area_m2"], layer["minimum_component_area_m2"])
            self.assertEqual(p["display_cell_m"], 20)
            self.assertLessEqual(p["maximum_supplied_uncertainty_m"], 2)
            self.assertLessEqual(p["maximum_depth_with_uncertainty_and_margin_ft"], 200)
            self.assertEqual(p["nbs_raster_sha256"], source_tiles[p["tile"]]["source_raster_sha256"])
            self.assertTrue(p["usgs_sources"])
            self.assertEqual(feature["geometry"]["type"], "Polygon")

if __name__ == "__main__":
    unittest.main()

"""Guard the distinction between measured seabed research and fishing targets."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NbsHardResearchPublicationTests(unittest.TestCase):
    def test_camera_evidence_matches_current_outlines_and_is_not_a_catch_claim(self):
        receipt = json.loads((ROOT / "dist/data/usgs-video-nbs-hard-overlap.json").read_text())
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        self.assertEqual(receipt["minimum_interior_clearance_m"], 25)
        for layer in receipt["layers"]:
            context = json.loads((ROOT / "dist/data" / layer["context_file"]).read_text())
            self.assertEqual(layer["context_compiled_at"], context["compiled_at"])
            self.assertEqual(layer["outline_count"], len(context["features"]))
            ids = {feature["properties"]["id"] for feature in context["features"]}
            for match in layer["matched_outlines"]:
                self.assertIn(match["outline_id"], ids)
                self.assertGreaterEqual(match["inside_display_outline"], match["interior_windows"])
                self.assertGreaterEqual(match["interior_windows"],
                                        match["rock_boulder_cobble_windows"] + match["sand_mud_windows"])
                self.assertTrue(match["observation_dates"])
                self.assertTrue(all(url.startswith("https://pubs.usgs.gov/")
                                    for url in match["source_urls"]))
        cape = next(layer for layer in receipt["layers"]
                    if layer["context_file"] == "northern-nbs-usgs-hard-research-context.geojson")
        self.assertEqual(cape["outlines_with_interior_camera_evidence"], 4)

    def test_cape_camera_centers_are_reconciled_with_original_survey_cells(self):
        camera = json.loads((ROOT / "dist/data/usgs-video-nbs-hard-overlap.json").read_text())
        original = json.loads((ROOT / "dist/data/h11975-original-camera-cell-review.json").read_text())
        cape = next(layer for layer in camera["layers"]
                    if layer["context_file"] == "northern-nbs-usgs-hard-research-context.geojson")
        context = json.loads((ROOT / "dist/data/northern-nbs-usgs-hard-research-context.geojson").read_text())
        self.assertEqual(original["context_compiled_at"], context["compiled_at"])
        self.assertFalse(original["fishing_target"])
        self.assertFalse(original["exportable"])
        self.assertEqual(original["total_camera_windows"],
                         sum(row["interior_windows"] for row in cape["matched_outlines"]))
        self.assertEqual(original["centers_on_qualified_original_cells"],
                         sum(row["centers_on_qualified_original_cells"] for row in original["outlines"]))
        source = {row["outline_id"]: row for row in cape["matched_outlines"]}
        for row in original["outlines"]:
            self.assertEqual(row["camera_windows"], source[row["outline_id"]]["interior_windows"])
            self.assertLessEqual(row["centers_on_qualified_original_cells"], row["camera_windows"])
            self.assertEqual(len(row["qualified_center_depths_ft"]),
                             row["centers_on_qualified_original_cells"])
            self.assertTrue(all(25 <= depth <= 200 for depth in row["qualified_center_depths_ft"]))

    def test_other_coast_layers_keep_native_depth_and_source_policy(self):
        statewide = json.loads((ROOT / "dist/data/nbs-statewide-usgs-hard-overlap-review.json").read_text())
        for coast_id, sectors, cell_m, max_features in (
                ("northern", {"humboldt-cape"}, 40, 10),
                ("san-francisco", {"arena-bodega", "bodega-reyes"}, 20, 10)):
            layer = json.loads((ROOT / f"dist/data/{coast_id}-nbs-usgs-hard-research-context.geojson").read_text())
            coast = next(row for row in statewide["coasts"] if row["coast_id"] == coast_id)
            tiles = {tile["tile"]: tile for sector in coast["source_review"]["sectors"]
                     for tile in sector["tiles"]}
            self.assertEqual(layer["scope"], f"{coast_id}-nbs-usgs-hard-research-context")
            self.assertEqual(layer["maximum_screen_uncertainty_m"], 1)
            self.assertGreater(len(layer["features"]), 0)
            self.assertLessEqual(len(layer["features"]), max_features)
            for feature in layer["features"]:
                p = feature["properties"]
                self.assertIn(p["sector_id"], sectors)
                self.assertEqual(p["display_cell_m"], cell_m)
                self.assertTrue(all(p[key] is False for key in (
                    "fishing_target", "exportable", "legal_clearance", "fish_confirmed",
                    "depth_qualified_for_target")))
                self.assertLessEqual(p["maximum_supplied_uncertainty_m"], 1)
                self.assertLessEqual(p["maximum_depth_with_uncertainty_and_margin_ft"], 200)
                self.assertEqual(p["nbs_raster_sha256"], tiles[p["tile"]]["source_raster_sha256"])

    def test_statewide_review_covers_each_sampled_sector_without_promoting_points(self):
        statewide = json.loads((ROOT / "dist/data/nbs-statewide-usgs-hard-overlap-review.json").read_text())
        sampled = json.loads((ROOT / "dist/data/nbs-statewide-multiple-camera-tile-review.json").read_text())
        self.assertEqual(statewide["status"], "research-leads-only")
        self.assertFalse(statewide["fishing_target"])
        self.assertFalse(statewide["exportable"])
        self.assertEqual(len(statewide["coasts"]), 5)
        reviewed = {sector["sector_id"]: sector for coast in statewide["coasts"]
                    for sector in coast["source_review"]["sectors"]}
        self.assertEqual(set(reviewed), {sector["sector_id"] for sector in sampled["sectors"]})
        for source_sector in sampled["sectors"]:
            actual = reviewed[source_sector["sector_id"]]
            self.assertEqual({tile["tile"] for tile in actual["tiles"]},
                             {tile["tile"] for tile in source_sector["reviewed_tiles"]})
            for tile in actual["tiles"]:
                self.assertLessEqual(tile["strict_1m_original_class3_unique_pixels"],
                                     tile["sensitivity_2m_original_class3_unique_pixels"])
                self.assertLessEqual(tile["sensitivity_2m_original_class3_unique_pixels"],
                                     tile["sensitivity_2m_measured_pixels_outside_closures"])
                self.assertEqual(tile["original_class_releases_not_audited"], [])
        northern = next(coast for coast in statewide["coasts"] if coast["coast_id"] == "northern")
        releases = {row["usgs_release_id"] for sector in northern["source_review"]["sectors"]
                    for tile in sector["tiles"] for row in tile["usgs_releases"]}
        self.assertNotIn("P9EC35PF", releases)  # Original CMECS identifies this Eureka class as jetty.

    def test_estero_layer_contains_only_screened_research_outlines(self):
        review = json.loads((ROOT / "dist/data/nbs-central-usgs-hard-overlap-review.json").read_text())
        layer = json.loads((ROOT / "dist/data/central-nbs-usgs-hard-research-context.geojson").read_text())
        self.assertEqual(review["status"], "research-leads-only")
        self.assertFalse(review["fishing_target"])
        self.assertFalse(review["exportable"])
        self.assertEqual(layer["scope"], "central-nbs-usgs-hard-research-context")
        self.assertEqual(layer["coast_id"], "central")
        self.assertEqual(layer["maximum_screen_uncertainty_m"], 2)
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

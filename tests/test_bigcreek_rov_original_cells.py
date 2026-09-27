"""Keep the Lopez historical ROV receipt out of fishing and export layers."""

import json
from pathlib import Path
import unittest

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts.audit_bigcreek_rov_original_cells import neighborhood_consistent


ROOT = Path(__file__).resolve().parents[1]


class BigCreekRovOriginalCellsTest(unittest.TestCase):
    def test_research_receipt_has_disjoint_source_tiers_and_no_positions(self):
        report = json.loads((ROOT / "dist/data/bigcreek-lopez-rov-original-cell-join.json").read_text())
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertFalse(report["chart_mllw_depth_and_upper_uncertainty_verified"])
        self.assertFalse(report["rov_bottom_position_error_bounded"])
        self.assertEqual(report["distinct_transect_labels_outside_screen"], 6)
        classes = report["outside_screen_by_derived_class"]
        self.assertEqual(sum(value["subunits"] for value in classes.values()),
                         report["counts"]["outside_mpa_plus_75m_screen"])
        self.assertEqual(sum(value.get("grid_2m_subunits", 0) + value.get("grid_5m_subunits", 0)
                             for value in classes.values()),
                         report["counts"]["outside_mpa_plus_75m_screen"])
        self.assertEqual(classes["derived_rough"]["same_class_and_band_within_10m_cell_centers"], 4)
        self.assertEqual(classes["derived_rough"]["same_class_and_band_within_25m_cell_centers"], 0)
        self.assertNotIn("coordinates", report)
        self.assertNotIn("features", report)
        self.assertNotIn("waypoints", report)

    def test_neighborhood_detects_single_class_and_depth_break(self):
        profile = {"driver": "GTiff", "height": 21, "width": 21, "count": 1,
                   "dtype": "float32", "crs": "EPSG:26910", "transform": from_origin(0, 42, 2, 2)}
        depth = np.full((21, 21), -70, dtype="float32")
        habitat = np.full((21, 21), -31, dtype="float32")
        with MemoryFile() as depth_memory, MemoryFile() as habitat_memory:
            with depth_memory.open(**profile) as source_depth, habitat_memory.open(**profile) as source_habitat:
                source_depth.write(depth, 1)
                source_habitat.write(habitat, 1)
                self.assertTrue(neighborhood_consistent(source_depth, source_habitat,
                                                        (21, 21), 10, -31, 2))
                habitat[10, 12] = -30
                source_habitat.write(habitat, 1)
                self.assertFalse(neighborhood_consistent(source_depth, source_habitat,
                                                         (21, 21), 10, -31, 2))
                source_habitat.write(np.full((21, 21), -31, dtype="float32"), 1)
                depth[10, 12] = -81
                source_depth.write(depth, 1)
                self.assertFalse(neighborhood_consistent(source_depth, source_habitat,
                                                         (21, 21), 10, -31, 2))


if __name__ == "__main__":
    unittest.main()

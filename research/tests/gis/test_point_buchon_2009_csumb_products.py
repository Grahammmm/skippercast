import json
import unittest

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from research.scripts.audit_point_buchon_2009_csumb_products import summarize_grid
from research.lib.receipts import RECEIPTS


class PointBuchon2009ProductsTests(unittest.TestCase):
    def test_exclusive_depth_slice_and_independent_class_counts(self):
        transform = from_origin(500000, 3900000, 2, 2)
        depth_values = np.array([[-61, -76.2], [-85.5, -90]], dtype="float32")
        class_values = np.array([[3, 2], [3, 1]], dtype="uint8")
        with MemoryFile() as depth_file, MemoryFile() as class_file:
            with depth_file.open(driver="GTiff", height=2, width=2, count=1,
                                 dtype="float32", crs="EPSG:26910", transform=transform,
                                 nodata=-9999) as dst:
                dst.write(depth_values, 1)
            with class_file.open(driver="GTiff", height=2, width=2, count=1,
                                 dtype="uint8", crs="EPSG:26910", transform=transform,
                                 nodata=0) as dst:
                dst.write(class_values, 1)
            with depth_file.open() as depth, class_file.open() as classes:
                result = summarize_grid(depth, classes, spacing=2,
                                        minimum_m=60.96, maximum_m=85)
        self.assertEqual(result["bands"]["200-250ft"]["usgs_hard_rugose_cells"], 1)
        self.assertEqual(result["bands"]["250-300ft"]["usgs_hard_flat_cells"], 1)
        self.assertEqual(sum(b["source_datum_depth_cells"] for b in result["bands"].values()), 2)

    def test_published_receipt_does_not_promote_source_datum_overlap(self):
        report = json.loads((RECEIPTS / "point-buchon-2009-csumb-original-overlap.json").read_text())
        self.assertEqual(report["inner_grid_metadata_survey_year"], 2009)
        self.assertEqual(report["bundled_bathy_trackline_year"], 2007)
        self.assertFalse(report["cell_acquisition_year_verified"])
        self.assertEqual(report["archive_label_cruise_year"], 2007)
        self.assertEqual(report["inner_grid_native_vertical_datum"],
                         "NAVD88 Geoid03 (inner original processing metadata)")
        self.assertFalse(report["source_product_upper_uncertainty_verified"])
        self.assertFalse(report["reuse_rights_resolved"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertFalse(report["exportable"])


if __name__ == "__main__":
    unittest.main()

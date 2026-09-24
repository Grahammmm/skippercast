import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from scripts.audit_regular_bag_camera import cell_review


class RegularBagCameraTests(unittest.TestCase):
    def test_original_cell_and_neighborhood_are_both_required(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.tif"
            with rasterio.open(path, "w", driver="GTiff", width=51, height=51,
                               count=2, dtype="float32", crs="EPSG:32610",
                               transform=from_origin(0, 76.5, 1.5, 1.5)) as grid:
                grid.write(np.full((51, 51), -40, dtype="float32"), 1)
                grid.write(np.full((51, 51), .4, dtype="float32"), 2)
            with rasterio.open(path) as grid:
                sample = cell_review(grid, 38.25, 38.25)
                self.assertEqual(sample["status"], "measured_qualified_cell")
                self.assertEqual(sample["qualified_neighborhood_fraction"], 1.0)
                self.assertEqual(cell_review(grid, -1, 38.25)["status"], "outside_grid")
            with rasterio.open(path, "r+") as grid:
                values = grid.read(1)
                values[25, 25] = np.nan
                grid.write(values, 1)
            with rasterio.open(path) as grid:
                self.assertEqual(cell_review(grid, 38.25, 38.25)["status"],
                                 "masked_or_ineligible_cell")


if __name__ == "__main__":
    unittest.main()

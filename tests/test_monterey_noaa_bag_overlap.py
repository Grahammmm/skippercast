import unittest

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box

from scripts.audit_monterey_noaa_bag_overlap import count_overlap


class OriginalBagOverlapTests(unittest.TestCase):
    def test_only_measured_uncertainty_cells_inside_outline_count(self):
        x, y = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform(-121.9, 36.67)
        image = np.full((2, 4, 4), 1_000_000, dtype="float32")
        image[0, :2, :2] = -70
        image[1, :2, :2] = .2
        image[1, 1, 1] = 1_000_000
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=4, height=4, count=2, dtype="float32",
                             crs="EPSG:32610", transform=from_origin(x - 16, y + 16, 8, 8),
                             nodata=1_000_000) as grid:
                grid.write(image)
                footprint = box(-121.9002, 36.6698, -121.8998, 36.6702)
                result = count_overlap(grid, footprint)
        self.assertEqual(result["measured_native_cells"], 3)
        self.assertEqual(result["nominal_200_300ft_cells"], 3)
        self.assertEqual(result["nominal_200_300ft_cells_below_300ft_with_product_uncertainty_and_margin"], 3)


if __name__ == "__main__":
    unittest.main()

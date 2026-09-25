import unittest

import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts.audit_usgs_ds552_san_pedro import validate_raster


class SanPedroOriginalRasterTests(unittest.TestCase):
    def check_grid(self, codes, *, crs="EPSG:32611", resolution=4):
        with MemoryFile() as file:
            with file.open(driver="GTiff", width=3, height=2, count=1, dtype="uint8",
                           crs=crs, transform=from_origin(380000, 3720000, resolution, resolution)) as ds:
                ds.write(np.array(codes, dtype="uint8").reshape(2, 3), 1)
            with file.open() as ds:
                return validate_raster(ds, 4)

    def test_reviewed_utm_grid_and_class_codes(self):
        self.assertEqual(set(np.unique(self.check_grid([0, 1, 2, 3, 4, 5]))), set(range(6)))

    def test_unreviewed_crs_resolution_and_class_fail_closed(self):
        for kwargs in ({"crs": "EPSG:4326"}, {"resolution": 8}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.check_grid([0, 1, 2, 3, 4, 5], **kwargs)
        with self.assertRaises(ValueError):
            self.check_grid([0, 1, 2, 3, 4, 6])


if __name__ == "__main__":
    unittest.main()

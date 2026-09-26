import unittest

import numpy as np

from scripts.audit_usgs_monterey_300_pixels import count_band


class NativeBandTests(unittest.TestCase):
    def test_positive_down_band_and_missing_cells(self):
        values = np.ma.array([-60.96, -75.0, -91.44, -91.5, -40, np.nan],
                             mask=[False, False, False, False, False, False])
        valid, band = count_band(values)
        self.assertEqual(valid, 5)
        self.assertEqual(band, 3)

    def test_masked_cell_not_zero_depth(self):
        values = np.ma.array([-75.0, -75.0], mask=[False, True])
        self.assertEqual(count_band(values), (1, 1))


if __name__ == "__main__":
    unittest.main()

import unittest

import numpy as np

from scripts.audit_regular_bag_300 import summarize


class RegularBagDepthScreenTests(unittest.TestCase):
    def test_mllw_depth_cap_includes_uncertainty_and_margin(self):
        elevation = np.array([[-6., -70., -88., -90., -100.]], dtype="float32")
        uncertainty = np.array([[.2, .5, .5, .5, .5]], dtype="float32")
        counts = summarize(elevation, uncertainty, 1)
        self.assertEqual(counts["measured_native_cells"], 5)
        self.assertEqual(counts["eligible_25_300ft_cells_with_margin"], 2)
        self.assertEqual(counts["nominal_200_300ft_cells_passing_300ft_uncertainty_margin"], 2)
        self.assertEqual(counts["eligible_25_200ft_cells_with_margin"], 0)

    def test_missing_uncertainty_does_not_become_zero(self):
        counts = summarize(np.array([[-75., -75.]], dtype="float32"),
                           np.array([[np.nan, .5]], dtype="float32"), 2)
        self.assertEqual(counts["measured_native_cells"], 1)
        self.assertEqual(counts["eligible_25_300ft_cells_with_margin"], 1)


if __name__ == "__main__":
    unittest.main()

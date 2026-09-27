import unittest

import numpy as np

from scripts.audit_point_conception_4m_patch_robustness import summarize_component


class PatchRobustnessTest(unittest.TestCase):
    def test_full_patch_uses_worst_cell_not_mean(self):
        elevation = np.array([[-65.0, -70.0], [-80.0, -75.0]])
        uncertainty = np.array([[0.2, 0.4], [0.8, 0.3]])
        summary = summarize_component(np.array([[True, True], [True, False]]), elevation, uncertainty)
        self.assertEqual(summary["native_cells"], 3)
        self.assertEqual(summary["maximum_supplied_product_uncertainty_m"], 0.8)
        self.assertEqual(summary["minimum_depth_minus_supplied_uncertainty_m"], 64.8)
        self.assertTrue(summary["all_cells_deeper_than_200ft_after_supplied_uncertainty"])
        self.assertEqual(summary["maximum_depth_plus_uncertainty_and_2m_allowance_m"], 82.8)
        self.assertEqual(summary["minimum_clearance_to_300ft_after_allowance_m"], 8.64)

    def test_missing_cells_fail(self):
        with self.assertRaises(ValueError):
            summarize_component(np.zeros((1, 1), dtype=bool), np.array([[-65.0]]), np.array([[0.2]]))


if __name__ == "__main__":
    unittest.main()

import unittest

import numpy as np

from scripts.audit_usgs_monterey_300_paired import paired_count


class OriginalPairTests(unittest.TestCase):
    def test_hard_code_requires_matching_original_class_pixel(self):
        depth = np.ma.array([[-75., -75., -75., -75.]], mask=[[False] * 4])
        codes = np.ma.array([[13, 12, 63, 13]], mask=[[False, False, False, True]])
        result = paired_count(depth, codes)
        self.assertEqual(result["native_navd88_band_cells"], 4)
        self.assertEqual(result["original_character_present_in_band_cells"], 3)
        self.assertEqual(result["paired_original_class3_hard_band_cells"], 2)


if __name__ == "__main__":
    unittest.main()

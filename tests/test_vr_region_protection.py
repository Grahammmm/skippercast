import unittest

from shapely.geometry import box

from scripts.audit_vr_region_protection import classify_footprint


class VariableGridMpaTest(unittest.TestCase):
    def test_full_partial_and_clear_footprints_differ(self):
        mpa = box(0, 0, 10, 10)
        self.assertEqual(classify_footprint(box(1, 1, 2, 2), mpa), 'fully_inside_mpa')
        self.assertEqual(classify_footprint(box(9, 9, 11, 11), mpa), 'intersects_mpa')
        self.assertEqual(classify_footprint(box(12, 12, 13, 13), mpa), 'outside_mpa')


if __name__ == '__main__':
    unittest.main()

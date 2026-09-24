import unittest

from shapely.geometry import Point, box
from shapely.strtree import STRtree

from scripts.audit_vr_camera_overlap import interior_camera_match


class VariableGridCameraTest(unittest.TestCase):
    def test_edge_camera_does_not_verify_grid_interior(self):
        polygons = [box(0, 0, 100, 100)]
        tree = STRtree(polygons)
        self.assertEqual(interior_camera_match(Point(3, 50), polygons, tree), 'native_grid_edge_held')
        self.assertEqual(interior_camera_match(Point(50, 50), polygons, tree), 'native_grid_interior')
        self.assertEqual(interior_camera_match(Point(150, 50), polygons, tree), 'outside_native_grid')


if __name__ == '__main__':
    unittest.main()

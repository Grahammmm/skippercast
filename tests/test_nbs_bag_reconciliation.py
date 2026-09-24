import unittest
from pathlib import Path

from shapely.geometry import Polygon
from shapely.strtree import STRtree

from scripts.reconcile_nbs_vr_bag_camera import bag_camera_status


class NbsBagReconciliationTest(unittest.TestCase):
    def test_original_grid_outside_and_edge_are_held(self):
        polygon = Polygon(((0, 0), (100, 0), (100, 100), (0, 100)))
        tree = STRtree([polygon])
        self.assertEqual(bag_camera_status(Path("not-opened.bag"), [polygon], [(0, 0)],
                                           tree, 150, 50), "outside_original_fine_grid")
        self.assertEqual(bag_camera_status(Path("not-opened.bag"), [polygon], [(0, 0)],
                                           tree, 5, 50), "original_fine_grid_edge_held")


if __name__ == "__main__":
    unittest.main()

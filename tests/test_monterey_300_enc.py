import unittest

from shapely.geometry import Point, box
from shapely.strtree import STRtree

from scripts.audit_monterey_300_enc import screen


class MontereyEncScreenTests(unittest.TestCase):
    def test_edge_proximity_holds_research_outline(self):
        hazards = [Point(180, 50), Point(1000, 1000)]
        result = screen(box(0, 0, 100, 100), hazards, STRtree(hazards))
        self.assertTrue(result["within_charted_danger_review_buffer"])
        self.assertEqual(result["nearest_charted_danger_in_scope_m"], 80)


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from research.scripts.audit_point_conception_8m_hard_overlap import cells_in_region
from affine import Affine
from research.lib.paths import ROOT


class PointConceptionEightMeterOverlapTests(unittest.TestCase):
    def test_original_eight_meter_screen_keeps_off_region_flat_area_out(self):
        report = json.loads((ROOT / "dist/data/point-conception-original-8m-hard-overlap.json").read_text())
        self.assertEqual(report["scope"], "point-conception-original-8m-mllw-usgs-class2-class3-aggregate-overlap")
        self.assertEqual(report["requested_region_southern_latitude"], 34.45)
        a, b = report["rows"]
        self.assertEqual((a["survey_id"], b["survey_id"]), ("H11952", "H11953"))
        self.assertEqual(a["class3_hard_rugged_two_cell_inset"]["inset_components_at_least_2500m2"], 0)
        self.assertEqual(a["requested_region_class3_raw_cells"], 564)
        self.assertEqual(a["requested_region_class3_inset_cells"], 41)
        self.assertEqual(a["class2_hard_flat_two_cell_inset"]["largest_inset_component_m2"], 516544)
        self.assertEqual(a["class2_hard_flat_two_cell_inset"]["retained_components_intersecting_requested_region"], 0)
        self.assertLess(a["class2_hard_flat_two_cell_inset"]["retained_component_northmost_latitude"], 34.45)
        self.assertEqual(b["class2_hard_flat_raw_overlap_cells"], 0)
        self.assertEqual(b["class3_hard_rugged_raw_overlap_cells"], 0)
        self.assertTrue(all(x["fishing_target"] is False and x["exportable"] is False for x in report["rows"]))
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertNotIn("geometry", report)

    def test_region_cell_counter_uses_cell_centers_and_explicit_bounds(self):
        import numpy as np
        mask = np.array([[True, False], [False, True]])
        transform = Affine(0.008, 0, -121, 0, -0.008, 35)
        count = cells_in_region(mask, transform, lambda x, y: (x, y), [-121, 34.9, -120.9, 34.99])
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()

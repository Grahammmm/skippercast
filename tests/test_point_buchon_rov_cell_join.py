import json
from pathlib import Path
import unittest

import numpy as np

from research.scripts.audit_point_buchon_rov_cell_join import source_depth_at
from research.lib.receipts import RECEIPTS


ROOT = Path(__file__).resolve().parents[1]


class FakeGrid:
    def __init__(self, value):
        self.value = value

    def sample(self, points, masked=False):
        assert masked and len(points) == 1
        yield np.ma.array([self.value], mask=[self.value is None])


class PointBuchonRovCellJoinTests(unittest.TestCase):
    def test_masked_cells_and_exclusive_grid_ranges(self):
        self.assertEqual(source_depth_at((0, 0), FakeGrid(None), FakeGrid(-90)), (90, 5))
        self.assertEqual(source_depth_at((0, 0), FakeGrid(-80), FakeGrid(-90)), (80, 2))
        self.assertEqual(source_depth_at((0, 0), FakeGrid(-85), FakeGrid(-86)), (86, 5))
        self.assertEqual(source_depth_at((0, 0), FakeGrid(None), FakeGrid(None)), (None, None))

    def test_public_receipt_stays_aggregate_and_unpromoted(self):
        receipt = json.loads((RECEIPTS / "point-buchon-rov-original-cell-join.json").read_text())
        self.assertEqual(receipt["scope"], "point-buchon-independent-original-cell-historical-rov-research-join")
        self.assertEqual(receipt["inward_block_sensitivity_m"]["0"]["original_grid_cell_in_source_depth_band"], 94)
        self.assertEqual(receipt["inward_block_sensitivity_m"]["25"]["original_grid_cell_in_source_depth_band"], 26)
        self.assertEqual(receipt["inward_block_sensitivity_m"]["0"]["distinct_transect_labels"], 5)
        self.assertEqual(receipt["publisher_character_accuracy"]["hard_flat"]["majority_percent"], 45.33)
        self.assertFalse(receipt["publisher_character_accuracy"]["held_out_validation"])
        self.assertFalse(receipt["rov_bottom_position_error_bounded"])
        self.assertFalse(receipt["chart_mllw_depth_and_upper_uncertainty_verified"])
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        for forbidden in ("coordinates", "geometry", "latitude", "longitude", "block_id"):
            self.assertNotIn(forbidden, receipt)


if __name__ == "__main__":
    unittest.main()

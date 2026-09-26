import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonBlueTopoOverlapTests(unittest.TestCase):
    def test_source_lineage_does_not_promote_interpolated_pixels(self):
        receipt = json.loads((ROOT / "dist/data/point-buchon-bluetopo-hard-cell-overlap.json").read_text())
        counts = receipt["contributor_center_counts"]
        self.assertEqual(sum(counts.values()), receipt["original_usgs_hard_rugose_cell_centers"])
        self.assertEqual(receipt["bluetopo_cells_with_finite_elevation_uncertainty_and_contributor"], 804337)
        self.assertEqual(counts["H05748"] + counts["H05832"], 16)
        self.assertEqual(receipt["bluetopo_measured_survey_contributor_centers"], 16)
        self.assertEqual(set(receipt["measured_source_dates"].values()), {"1934-01-01"})
        self.assertEqual(len(receipt["tiles"]), 8)
        self.assertEqual(receipt["qualified_waypoints"], 0)
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])


if __name__ == "__main__":
    unittest.main()

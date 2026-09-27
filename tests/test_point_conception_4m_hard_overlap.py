import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PointConceptionRuggedOverlapTests(unittest.TestCase):
    def test_two_research_components_stay_unpublished(self):
        result = json.loads((ROOT / "dist/data/point-conception-original-4m-rugged-overlap.json").read_text())
        self.assertEqual(result["scope"], "point-conception-original-4m-mllw-usgs-class3-aggregate-overlap")
        self.assertEqual(result["total_inset_components_at_least_2500m2"], 2)
        self.assertEqual({row["survey_id"] for row in result["rows"]}, {"H11952", "H11953"})
        self.assertEqual([row["depth_cells_on_two_cell_inset_class3"] for row in result["rows"]],
                         [4514, 236])
        self.assertTrue(all(row["fishing_target"] is False and row["exportable"] is False
                            for row in result["rows"]))
        self.assertFalse(result["fishing_target"])
        self.assertFalse(result["exportable"])
        self.assertNotIn("geometry", result)
        self.assertNotIn("coordinates", result)


if __name__ == "__main__":
    unittest.main()

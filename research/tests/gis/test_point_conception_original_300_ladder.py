import json
import unittest

from research.scripts import audit_point_conception_original_300_ladder as ladder
from research.lib.paths import ROOT


class PointConceptionDepthLadderTests(unittest.TestCase):
    def test_pinned_original_tiers_include_deeper_research_cells(self):
        report = json.loads((ROOT / "dist/data/point-conception-original-bag-depth-ladder.json").read_text())
        self.assertEqual(report["scope"], "point-conception-h11952-h11953-eight-original-mllw-bag-depth-tiers")
        self.assertEqual(len(report["sources"]), 8)
        self.assertEqual(report["nominal_200_to_300ft_cells"], 3990509)
        self.assertEqual(report["nominal_200_to_300ft_4m_cells"], 3318707)
        self.assertTrue(all(row["vertical_datum"] == "MLLW" and row["uncertainty_type"] == "productUncert"
                            for row in report["sources"]))
        self.assertTrue(all(row["fishing_target"] is False and row["exportable"] is False
                            for row in report["sources"]))
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])

    def test_all_eight_files_and_hashes_are_pinned(self):
        self.assertEqual(sum(len(files) for files in ladder.SOURCE_HASHES.values()), 8)
        self.assertEqual({survey for survey in ladder.SOURCE_HASHES}, {"H11952", "H11953"})
        self.assertTrue(all(len(sha) == 64 for files in ladder.SOURCE_HASHES.values()
                            for _, sha in files))


if __name__ == "__main__":
    unittest.main()

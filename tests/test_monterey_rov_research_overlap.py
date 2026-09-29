import unittest
from pathlib import Path

from research.scripts.audit_monterey_rov_research_overlap import build


class HistoricalRovOverlapTest(unittest.TestCase):
    def test_open_reference_subunits_are_evidence_without_spot_promotion(self):
        source = Path("var/review/rov-zenodo-10929417.csv")
        if not source.exists():
            self.skipTest("run after fetching the pinned original ROV release")
        result = build(source)
        self.assertEqual(result["source_rows_checked"], 133506)
        self.assertEqual(len(result["outlines"]), 17)
        self.assertEqual(result["outlines"]["023"]["interior_sensitivity"]["25"]["subunits"], 28)
        self.assertEqual(result["outlines"]["023"]["interior_sensitivity"]["25"]["distinct_transect_labels"], 10)
        self.assertEqual(result["outlines"]["072"]["interior_sensitivity"]["0"]["subunits"], 15)
        self.assertEqual(result["outlines"]["072"]["interior_sensitivity"]["10"]["subunits"], 3)
        self.assertEqual(result["outlines"]["072"]["interior_sensitivity"]["25"]["subunits"], 0)
        self.assertEqual(result["outlines"]["046"]["interior_sensitivity"]["0"]["subunits"], 0)
        self.assertFalse(result["fishing_target"])
        self.assertFalse(result["outlines"]["023"]["mllw_depth_qualified"])
        self.assertFalse(result["outlines"]["072"]["source_position_error_bounded"])


if __name__ == "__main__":
    unittest.main()

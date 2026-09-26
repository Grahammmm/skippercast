import json
from pathlib import Path
import unittest

import numpy as np

from scripts.audit_central_deep_original_300 import MAX_M, depth_summary


ROOT = Path(__file__).resolve().parents[1]


class OriginalDeepwaterScreenTests(unittest.TestCase):
    def test_exact_depth_boundary_is_counted(self):
        values = np.array([-MAX_M, -MAX_M - .001, np.nan, 100, -99999])
        summary = depth_summary(values)
        self.assertEqual(summary["valid_cells"], 2)
        self.assertEqual(summary["nominal_200_300ft_cells"], 1)
        self.assertEqual(summary["cells_at_or_shallower_than_300ft"], 1)

    def test_receipt_refutes_only_pinned_source_files(self):
        report = json.loads((ROOT / "dist/data/central-deep-original-300-refutation.json").read_text())
        self.assertEqual({row["survey_id"] for row in report["sources"]}, {"H13152", "W00479"})
        self.assertFalse(report["fishing_target"])
        for row in report["sources"]:
            self.assertGreater(row["active_refinement_records"], row["native_refinements"]["valid_cells"])
            self.assertGreater(row["trailing_padding_records_ignored"], 0)
            self.assertEqual(row["native_refinements"]["cells_at_or_shallower_than_300ft"], 0)
            self.assertGreater(row["native_refinements"]["shallowest_depth_m_mllw"], MAX_M)


if __name__ == "__main__":
    unittest.main()

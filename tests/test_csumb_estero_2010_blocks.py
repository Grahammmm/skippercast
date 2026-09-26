import json
from pathlib import Path
import unittest

from scripts.audit_csumb_estero_2010_blocks import SOURCES, original_grid


ROOT = Path(__file__).resolve().parents[1]


class CsumbEsteroOriginalBlocksTest(unittest.TestCase):
    def test_changed_archive_rejected_before_unpacking(self):
        with self.assertRaisesRegex(ValueError, "original archive changed"):
            original_grid(Path(__file__), 12, ROOT / "var/review")

    def test_published_result_cannot_qualify_deeper_blocks(self):
        receipt = json.loads((ROOT / "dist/data/csumb-scc-2010-estero-original-block-coverage.json").read_text())
        self.assertEqual(receipt["scope"], "csumb-scc-2010-estero-original-research-block-coverage")
        self.assertEqual(receipt["private_block_count"], 60)
        self.assertEqual(receipt["qualified_waypoints"], 0)
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        self.assertEqual(len(receipt["source_results"]), 2)
        for row in receipt["source_results"]:
            sid = int(row["survey_id"].removeprefix("SCC_Block"))
            self.assertEqual(row["archive_sha256"], SOURCES[sid]["archive_sha256"])
            self.assertEqual(row["bands"]["250-300ft"]["measured_2010_cells"], 0)
            self.assertEqual(row["bands"]["200-250ft"]["blocks_with_measured_2010_cells"], 4)
            self.assertGreater(row["nominal_2010_2012_depth_comparison"]["matched_native_cells"], 5000)


if __name__ == "__main__":
    unittest.main()

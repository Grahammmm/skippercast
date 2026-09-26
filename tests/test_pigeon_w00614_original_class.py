import json
from pathlib import Path
import unittest

import numpy as np

from scripts import audit_pigeon_w00614_original_class as audit


ROOT = Path(__file__).resolve().parents[1]


class PigeonOriginalClassTests(unittest.TestCase):
    def test_nodata_must_not_turn_into_hard_flat(self):
        placed = np.array([[-128, 2, 3], [-128, 1, 53]], dtype="int16")
        eligible = np.array([[True, True, True], [True, False, True]])
        self.assertEqual(audit.classified_counts(placed, eligible), {
            "classified": 3, "hard_flat": 1, "hard_rugose": 2, "soft_flat": 0})

    def test_original_source_receipt_keeps_zero_overlap_on_hold(self):
        binding = json.loads((ROOT / "catalog/pigeon-w00614-original-class-binding.json").read_text())
        receipt = json.loads((ROOT / "dist/data/w00614-pigeon-original-character-overlap.json").read_text())
        self.assertEqual(receipt["scope"], binding["scope"])
        self.assertEqual(receipt["depth_source_sha256"], binding["bag_sha256"])
        self.assertEqual(receipt["character_source_sha256"], binding["character_sha256"])
        self.assertEqual(receipt["counts"]["qualified_depth_cells"], 141331)
        self.assertEqual(receipt["counts"]["classified"], 0)
        self.assertFalse(receipt["exportable"])
        self.assertEqual(receipt["qualified_waypoints"], 0)


if __name__ == "__main__":
    unittest.main()

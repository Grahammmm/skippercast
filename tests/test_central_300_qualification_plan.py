import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import build_central_300_qualification_plan as plan


ROOT = Path(__file__).resolve().parents[1]


class QualificationPlanTests(unittest.TestCase):
    def test_all_sectors_and_ten_tracks_keep_deeper_targets_on_hold(self):
        result = plan.build(ROOT)
        self.assertEqual(len(result["sectors"]), 6)
        self.assertEqual(len(result["tracks"]), 10)
        self.assertEqual(len(result["release_gate_ids"]), 6)
        self.assertEqual({s["sector_id"] for s in result["sectors"]}, set(plan.SECTOR_OVERRIDES))
        for sector in result["sectors"]:
            self.assertIsNone(sector["fishing_rank"])
            self.assertFalse(sector["exportable"])
            self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)
            self.assertEqual(len(sector["tracks"]), 10)
            self.assertTrue(all(not track["release_gate_satisfied"] for track in sector["tracks"]
                                if track["id"] in result["release_gate_ids"]))
        pigeon = next(s for s in result["sectors"] if s["sector_id"] == "pigeon-monterey")
        self.assertEqual(pigeon["native_cell_evidence"], "measured-mllw-substrate-unpaired")
        self.assertIn("dist/data/w00614-original-300-pigeon-monterey-review.json", pigeon["source_receipts"])
        self.assertIn("dist/data/w00614-pigeon-original-character-overlap.json", pigeon["source_receipts"])
        estero = next(s for s in result["sectors"] if s["sector_id"] == "cambria-morro")
        self.assertEqual(estero["native_cell_evidence"], "source-datum-only")
        self.assertIn("CARIS TPU", estero["next_acquisition"])
        self.assertIn("dist/data/estero-2012-vdatum-spatial-diagnostic.json", estero["source_receipts"])
        conception = next(s for s in result["sectors"] if s["sector_id"] == "morro-conception")
        self.assertIn("dist/data/central-deep-original-300-refutation.json", conception["source_receipts"])
        self.assertIn("other original MLLW surveys", conception["next_acquisition"])

    def test_new_deep_waypoint_requires_manual_reconciliation(self):
        original = plan.load

        def changed(root, relative):
            data = original(root, relative)
            if relative == "dist/data/central-coverage-ledger-v1.json":
                data = copy.deepcopy(data)
                data["totals"]["qualified_targets_200_to_300ft"] = 1
            return data

        with patch.object(plan, "load", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "reconcile the qualification manifest"):
                plan.build(ROOT)

    def test_point_buchon_datum_change_requires_review(self):
        original = plan.load

        def changed(root, relative):
            data = original(root, relative)
            if relative == "dist/data/point-buchon-original-paired-200-300ft-review.json":
                data = copy.deepcopy(data)
                data["native_depth_datum"] = "MLLW"
            return data

        with patch.object(plan, "load", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed status"):
                plan.build(ROOT)


if __name__ == "__main__":
    unittest.main()

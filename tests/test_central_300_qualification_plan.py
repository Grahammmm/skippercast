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
        self.assertEqual({track["id"] for track in result["tracks"]}, set(plan.TRACK_PROTOCOLS))
        self.assertTrue(all(track["acceptance_test"] and track["refresh_trigger"]
                            for track in result["tracks"]))
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
        self.assertIn("dist/data/w00614-usgs-video-observation-gap.json", pigeon["source_receipts"])
        self.assertIn("dist/data/w00614-noaa-sh1809-observation-gap.json", pigeon["source_receipts"])
        monterey = next(s for s in result["sectors"] if s["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-17-noaa-bag-catalog-gap.json", monterey["source_receipts"])
        self.assertIn("dist/data/monterey-17-bluetopo-contributor-pixels.json", monterey["source_receipts"])
        self.assertIn("dist/data/monterey-1995-original-multibeam-overlap.json", monterey["source_receipts"])
        self.assertIn("dist/data/monterey-1998-original-em300-overlap.json", monterey["source_receipts"])
        self.assertIn("dist/data/monterey-2013-merge-lineage-gap.json", monterey["source_receipts"])
        conception = next(s for s in result["sectors"] if s["sector_id"] == "morro-conception")
        self.assertIn("dist/data/point-conception-original-8m-hard-overlap.json", conception["source_receipts"])
        self.assertIn("Full_DataInventory.xlsx", monterey["next_acquisition"])
        self.assertIn("catalog/candidates/tnc-mlml-pigeon-video-lander.json", pigeon["source_receipts"])
        self.assertIn("video-lander drop table", pigeon["next_acquisition"])
        self.assertIn("actual", pigeon["next_acquisition"])
        estero = next(s for s in result["sectors"] if s["sector_id"] == "cambria-morro")
        self.assertEqual(estero["native_cell_evidence"], "source-datum-only")
        self.assertIn("CARIS TPU", estero["next_acquisition"])
        self.assertIn("dist/data/estero-2012-vdatum-spatial-diagnostic.json", estero["source_receipts"])
        self.assertIn("dist/data/estero-2012-public-release-inventory.json", estero["source_receipts"])
        south_sur = next(s for s in result["sectors"] if s["sector_id"] == "sur-san-simeon")
        self.assertIn("catalog/candidates/cdfw-mare-ciap-2016-central-original-rov.json", south_sur["source_receipts"])
        self.assertIn("dist/data/ciap-2016-central-rov-public-service-audit.json", south_sur["source_receipts"])
        self.assertIn("dist/data/ciap-2016-central-video-private-block-overlap.json", south_sur["source_receipts"])
        self.assertIn("dist/data/bss03-video-grid-overlap.json", south_sur["source_receipts"])
        self.assertIn("dist/data/bss03-camera-access-triage.json", south_sur["source_receipts"])
        self.assertIn("dist/data/bss03-original-vessel-tpu-inputs.json", south_sur["source_receipts"])
        self.assertIn("dist/data/bss03-caris-original-tpe-member-lead.json", south_sur["source_receipts"])
        self.assertEqual(next(t for t in south_sur["tracks"] if t["id"] == "independent-substrate")["stage"], "research-evidence")
        self.assertEqual(next(t for t in south_sur["tracks"] if t["id"] == "legal-chart-access")["stage"], "partial-release-evidence")
        self.assertFalse(south_sur["independent_groundtruth_at_candidate_scale"])
        conception = next(s for s in result["sectors"] if s["sector_id"] == "morro-conception")
        self.assertIn("dist/data/point-buchon-private-block-access-screen.json", conception["source_receipts"])
        self.assertIn("dist/data/point-buchon-vdatum-grid-api-bridge.json", conception["source_receipts"])
        self.assertIn("dist/data/central-dataone-rov-300ft-spot-precision.json", conception["source_receipts"])
        self.assertIn("dist/data/central-deep-original-300-refutation.json", conception["source_receipts"])
        self.assertIn("dist/data/point-buchon-noaa-catalog-envelope-gap.json", conception["source_receipts"])
        self.assertIn("dist/data/point-buchon-bluetopo-hard-cell-overlap.json", conception["source_receipts"])
        self.assertIn("dist/data/point-buchon-2007-ncei-multibeam-lead.json", conception["source_receipts"])
        self.assertIn("dist/data/point-buchon-2007-ncei-line-index.json", conception["source_receipts"])
        self.assertIn("dist/data/point-buchon-2007-ncei-valid-beam-overlap.json", conception["source_receipts"])
        self.assertIn("dist/data/point-buchon-2007-caris-prefix-lead.json", conception["source_receipts"])
        self.assertIn("processed GSF", conception["next_acquisition"])
        self.assertIn("2007", conception["reviewed_lead"])
        self.assertIn("not independent 2009 acquisition", conception["limiting_evidence"])

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

    def test_pigeon_lander_lead_cannot_silently_become_spot_evidence(self):
        original = plan.load

        def changed(root, relative):
            data = original(root, relative)
            if relative == "catalog/candidates/tnc-mlml-pigeon-video-lander.json":
                data = copy.deepcopy(data)
                data["spatial"]["w00614_cell_overlap_verified"] = True
            return data

        with patch.object(plan, "load", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "original lander source status changed"):
                plan.build(ROOT)

    def test_mare_report_cannot_silently_become_candidate_scale_evidence(self):
        original = plan.load

        def changed(root, relative):
            data = original(root, relative)
            if relative == "catalog/candidates/cdfw-mare-ciap-2016-central-original-rov.json":
                data = copy.deepcopy(data)
                data["spatial"]["candidate_cell_overlap_verified"] = True
            return data

        with patch.object(plan, "load", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "CDFW/MARE original 2016 ROV source status changed"):
                plan.build(ROOT)


if __name__ == "__main__":
    unittest.main()

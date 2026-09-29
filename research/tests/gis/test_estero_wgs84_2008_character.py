"""Direct-datum Estero/class join must preserve weak-evidence release holds."""

import json
import unittest

from research.scripts.audit_estero_wgs84_2008_character import checked_offsets, disk
from research.lib.receipts import RECEIPTS
from research.lib.paths import ROOT


class EsteroWgs84CharacterTest(unittest.TestCase):
    def test_receipt_is_aggregate_and_unqualified(self):
        report = json.loads((RECEIPTS / "estero-wgs84-2008-character-sensitivity.json").read_text())
        self.assertFalse(report["full_cellwise_mllw_surface_verified"])
        self.assertFalse(report["source_product_upper_uncertainty_verified"])
        self.assertFalse(report["cross_survey_horizontal_registration_bounded"])
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertNotIn("features", report)
        self.assertNotIn("coordinates", report)
        bands = report["by_prior_research_band"]
        for band in bands.values():
            self.assertLessEqual(band["rugose_class_stable_within_25m_cell_centers"],
                                 band["rugose_class_stable_within_10m_cell_centers"])
            self.assertLessEqual(band["rugose_class_stable_within_10m_cell_centers"],
                                 band["hard_rugose_cells"])
            self.assertLessEqual(band["hard_rugose_cells"], band["nominal_200_300ft_cells"])
            self.assertLessEqual(band["largest_within_block_25m_stable_component_cells"],
                                 band["rugose_class_stable_within_25m_cell_centers"])
            if band["within_block_25m_stable_component_count"] == 0:
                self.assertEqual(band["largest_within_block_25m_stable_component_cells"], 0)

    def test_circle_uses_native_two_meter_cell_centers(self):
        ten = disk(10)
        self.assertTrue(ten[5, 5])
        self.assertTrue(ten[5, 0])
        self.assertFalse(ten[0, 0])
        self.assertGreater(disk(25).sum(), ten.sum())

    def test_changed_vdatum_frame_fails_closed(self):
        blocks = {"features": [{"properties": {"band": "250-300ft"}} for _ in range(60)]}
        private = {"scope": "private-estero-direct-vdatum-blocks", "blocks": [
            {"block_index": index, "band": "250-300ft",
             "nominal_center_offset_200_300ft_cells": 1,
             "vdatum": {"offset_m": 35.8, "transform_uncertainty_m": 0.08,
                        "response": {"s_h_frame": "WGS84_G1150", "t_v_frame": "MLLW"}}}
            for index in range(60)]}
        receipt = {"scope": "estero-2012-original-wgs84-direct-vdatum-research",
                   "sample_count": 60,
                   "by_prior_nominal_band": {"250-300ft": {"nominal_center_offset_200_300ft_cells": 60}}}
        self.assertEqual(len(checked_offsets(blocks, private, receipt)), 60)
        private["blocks"][0]["vdatum"]["response"]["s_h_frame"] = "NAD83_2011"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            checked_offsets(blocks, private, receipt)


if __name__ == "__main__":
    unittest.main()

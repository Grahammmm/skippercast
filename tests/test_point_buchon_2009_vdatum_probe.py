import json
from pathlib import Path
import unittest

from scripts import audit_point_buchon_2009_vdatum_probe as probe


ROOT = Path(__file__).resolve().parents[1]


class PointBuchon2009VDatumProbeTests(unittest.TestCase):
    def test_official_model_samples_do_not_become_depth_clearance(self):
        receipt = json.loads((ROOT / "dist/data/point-buchon-2009-conditional-vdatum-probes.json").read_text())
        self.assertEqual(receipt["official_regional_archive_sha256"], probe.ARCHIVE_SHA256)
        self.assertEqual(receipt["private_block_count"], 181)
        self.assertEqual(receipt["sample_count"], probe.SAMPLE_COUNT)
        self.assertEqual(receipt["conditional_navd88_zero_to_mllw_offset_m"], [0.129, 0.149])
        self.assertEqual(receipt["api_reported_transformation_uncertainty_m"], [0.097, 0.097])
        self.assertEqual(receipt["alternate_nad83_1986_probe"]["error_code"], 412)
        self.assertFalse(receipt["source_horizontal_realization_and_epoch_verified"])
        self.assertFalse(receipt["source_product_upper_uncertainty_verified"])
        self.assertFalse(receipt["full_source_cell_conversion"])
        self.assertEqual(receipt["qualified_waypoints"], 0)
        self.assertFalse(receipt["exportable"])

    def test_retrieval_time_is_ignored_but_model_change_is_not(self):
        receipt = json.loads((ROOT / "dist/data/point-buchon-2009-conditional-vdatum-probes.json").read_text())
        changed = {**receipt, "checked_at": "later"}
        self.assertEqual(probe.stable(receipt), probe.stable(changed))
        changed["conditional_navd88_zero_to_mllw_offset_m"] = [0.129, 0.150]
        self.assertNotEqual(probe.stable(receipt), probe.stable(changed))


if __name__ == "__main__":
    unittest.main()

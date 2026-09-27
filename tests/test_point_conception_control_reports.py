import tempfile
from pathlib import Path
import unittest

from scripts.audit_point_conception_control_reports import build, verified_pdf


class PointConceptionControlReportTest(unittest.TestCase):
    def test_pinned_noaa_reports_do_not_become_position_bound(self):
        report = build()
        self.assertEqual(report["survey_ids"], ["H11952", "H11953"])
        self.assertEqual(report["position_model_base_navigation_input_m"], 0.1)
        self.assertTrue(report["per_line_dynamic_rms_overrides_documented"])
        self.assertFalse(report["position_model_base_is_total_horizontal_bound"])
        self.assertFalse(report["usgs_character_to_bag_horizontal_registration_bounded"])
        self.assertFalse(report["fishing_target"])

    def test_missing_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                verified_pdf("H11952_tide_note", Path(directory), fetch=False)


if __name__ == "__main__":
    unittest.main()

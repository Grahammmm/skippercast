import json
import tempfile
from pathlib import Path
import unittest

from scripts.audit_point_conception_control_reports import CACHE, OUTPUT, SOURCES, build, verified_pdf


def _cached_sources_present():
    return all((CACHE / url.rsplit("/", 1)[-1]).exists() for url, _, _ in SOURCES.values())


class PointConceptionControlReportTest(unittest.TestCase):
    @unittest.skipUnless(_cached_sources_present(),
                         "Pinned NOAA PDFs are cached in var/review (gitignored); run the audit with --fetch locally")
    def test_pinned_noaa_reports_do_not_become_position_bound(self):
        report = build()
        self.assertEqual(report["survey_ids"], ["H11952", "H11953"])
        self.assertEqual(report["position_model_base_navigation_input_m"], 0.1)
        self.assertTrue(report["per_line_dynamic_rms_overrides_documented"])
        self.assertFalse(report["position_model_base_is_total_horizontal_bound"])
        self.assertFalse(report["usgs_character_to_bag_horizontal_registration_bounded"])
        self.assertFalse(report["fishing_target"])

    def test_published_review_is_not_a_position_bound(self):
        report = json.loads(OUTPUT.read_text())
        self.assertEqual(report["survey_ids"], ["H11952", "H11953"])
        self.assertFalse(report["position_model_base_is_total_horizontal_bound"])
        self.assertFalse(report["usgs_character_to_bag_horizontal_registration_bounded"])
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])

    def test_missing_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                verified_pdf("H11952_tide_note", Path(directory), fetch=False)


if __name__ == "__main__":
    unittest.main()

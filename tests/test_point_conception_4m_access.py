import json
from pathlib import Path
import unittest

from scripts.audit_point_conception_4m_access import (
    feature_digest, fresh, verify_baseline, vandenberg_zone_7,
)
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parents[1]


class PointConceptionFourMeterAccessTests(unittest.TestCase):
    def test_dated_full_component_screen_stays_research_only(self):
        report = json.loads((ROOT / "dist/data/point-conception-original-4m-access-screen.json").read_text())
        self.assertEqual(report["scope"], "point-conception-two-original-4m-components-current-gis-screen")
        self.assertEqual(len(report["components"]), 2)
        self.assertEqual(report["review_margin_m"], 100)
        self.assertEqual(report["components_held_by_mapped_gis"], 0)
        self.assertEqual(report["cdfw_mpa_features"], 155)
        self.assertEqual(report["noaa_enc_danger_features"], 87)
        self.assertTrue(all(row["fishing_target"] is False and row["exportable"] is False
                            for row in report["components"]))
        self.assertTrue(all(row["inside_approximate_vandenberg_zone_7_with_100m_margin"]
                            and row["launch_closure_status_for_trip_date"] == "unverified"
                            for row in report["components"]))
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertNotIn("geometry", report)
        self.assertNotIn("coordinates", report)

    def test_source_feature_digest_is_stable_and_freshness_fails_closed(self):
        self.assertEqual(feature_digest([{"a": 1, "b": 2}]),
                         feature_digest([{"b": 2, "a": 1}]))
        with self.assertRaisesRegex(ValueError, "stale"):
            fresh("2020-01-01T00:00:00Z")

    def test_changed_official_features_fail_baseline(self):
        report = json.loads((ROOT / "dist/data/point-conception-original-4m-access-screen.json").read_text())
        changed = {**report, "source_feature_sha256": {**report["source_feature_sha256"],
                                                        "cdfw_mpa": "0" * 64}}
        with self.assertRaisesRegex(ValueError, "source_feature_sha256"):
            verify_baseline(changed, report)

    def test_regulatory_zone_does_not_imply_a_permanent_closure(self):
        zone = vandenberg_zone_7()
        self.assertTrue(zone.is_valid)
        self.assertTrue(zone.covers(Point(-120.54, 34.46)))
        self.assertFalse(zone.covers(Point(-120.54, 34.60)))


if __name__ == "__main__":
    unittest.main()

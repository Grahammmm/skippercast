"""An ENC seabed query cannot promote a Point Conception fishing patch."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from research.scripts.audit_point_conception_enc_seabed_gap import query_one


ROOT = Path(__file__).resolve().parents[1]


class PointConceptionEncSeabedGapTest(unittest.TestCase):
    def test_aggregate_receipt_keeps_two_patches_unqualified(self):
        report = json.loads((ROOT / "dist/data/point-conception-original-4m-enc-seabed-gap.json").read_text())
        self.assertEqual(set(report["by_survey"]), {"H11952", "H11953"})
        self.assertEqual(report["reviewed_scale_bands"], ["enc_harbour", "enc_approach", "enc_coastal"])
        for row in report["by_survey"].values():
            self.assertEqual(row["queried_layers"], 8)
            self.assertEqual(row["charted_seabed_features_in_100m_envelope"], 0)
        self.assertFalse(report["independent_bottom_verified"])
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertNotIn("features", report)
        self.assertNotIn("coordinates", report)

    def test_a_new_chart_feature_is_only_a_lead(self):
        with patch("research.scripts.audit_point_conception_enc_seabed_gap.query_layer") as mocked:
            mocked.return_value = ([{"geometry": {"type": "Point", "coordinates": [-120, 34]}}],
                                   {"count_sha256": "count", "data_sha256": "data"})
            row = query_one(("H11952", (-121, 34, -120, 35), "enc_coastal",
                             "Seabed_Area_point", 56))
        self.assertEqual(row["count_within_100m_envelope"], 1)
        self.assertNotIn("geometry", row)
        self.assertNotIn("coordinates", row)


if __name__ == "__main__":
    unittest.main()

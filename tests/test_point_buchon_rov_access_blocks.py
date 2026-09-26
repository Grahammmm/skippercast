import json
from pathlib import Path
import unittest
from collections import Counter
from datetime import datetime, timezone

from shapely.geometry import box

from scripts.audit_point_buchon_rov_access_blocks import build
from scripts.check_point_buchon_rov_access_change import compare


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonRovAccessBlocksTest(unittest.TestCase):
    def test_whole_block_margin_holds_near_mpa(self):
        # The screen must inspect the full block plus margin, not just a ROV center.
        from unittest.mock import patch
        blocks = {(100, 100): {"subunits": 2, "lingcod_seen": 1, "vermilion_seen": 0,
                               "centers_on_at_or_over_80m_5m_source": 0,
                               "classes": Counter({"hard_rugose": 2}), "years": {2020}}}
        geometry = box(10150, 10020, 10160, 10080)
        mpa = {"status": "research-closure-screen-only", "checked_at": "2026-09-26T12:00:00Z",
               "source_url": "https://example.test/mpa", "features": []}
        federal = {"retrieved_at": "2026-09-26T12:00:00Z", "service_url": "https://example.test/federal",
                   "features": []}
        enc = {"checked_at": "2026-09-26T12:00:00Z", "source_url": "https://example.test/enc",
               "features": [], "query_receipts": []}
        with patch("scripts.audit_point_buchon_rov_access_blocks.closures",
                   return_value=(box(9000, 9000, 11000, 11000), box(9000, 9000, 11000, 11000),
                                 geometry, box(0, 0, 1, 1), box(0, 0, 1, 1), 10)):
            public, private = build(blocks, mpa, federal, enc,
                                    now=datetime(2026, 9, 26, 12, tzinfo=timezone.utc))
        self.assertEqual(public["totals"]["mpa_margin_blocks"], 1)
        self.assertEqual(public["qualified_waypoints"], 0)
        self.assertFalse(private["features"][0]["properties"]["exportable"])

    def test_published_receipt_and_refresh_guard(self):
        report = json.loads((ROOT / "dist/data/point-buchon-rov-access-triage.json").read_text())
        self.assertEqual(report["totals"]["blocks"], 26)
        self.assertEqual(report["totals"]["subunits"], 183)
        self.assertEqual(report["totals"]["hard_rugose_subunits"], 58)
        self.assertEqual(report["totals"]["centers_on_at_or_over_80m_5m_source"], 0)
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertNotIn("features", report)
        self.assertTrue(compare(report, dict(report)))
        changed = json.loads(json.dumps(report))
        changed["official_geometry_sha256"]["cdfw_mpas"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source or screening change"):
            compare(report, changed)


if __name__ == "__main__":
    unittest.main()

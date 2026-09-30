"""Bounded catalog discovery must never promote a fishing location."""

import json
from pathlib import Path
import unittest

from shapely.geometry import box, mapping

from research.scripts.audit_estero_noaa_bag_catalog_gap import build
from research.lib.receipts import RECEIPTS
from research.lib.paths import ROOT


class EsteroNoaaBagCatalogGapTest(unittest.TestCase):
    def test_published_receipt_is_research_only(self):
        report = json.loads((RECEIPTS / "estero-noaa-bag-catalog-gap.json").read_text())
        self.assertEqual(report["bag_survey_count"], 0)
        self.assertEqual(report["bag_survey_ids_returned"], [])
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertNotIn("features", report)
        self.assertNotIn("waypoints", report)

    def test_fresh_catalog_hit_stays_unqualified(self):
        blocks = {"crs": "EPSG:32610", "features": [
            {"geometry": mapping(box(679000 + i * 10, 3917000, 679010 + i * 10, 3917010))}
            for i in range(60)]}
        receipt = {"scope": "estero-2012-original-wgs84-direct-vdatum-research",
                   "private_block_fingerprint": "synthetic", "sample_count": 60,
                   "fishing_target": False}

        def catalog(sectors):
            self.assertEqual(len(sectors), 1)
            return {"health": {"status": "ok"}, "source_url": "https://example.org/catalog",
                    "sectors": [{"status": "ok", "raw_sha256": "test-hash",
                                 "request_url": "https://example.org/query",
                                 "surveys": [{"id": "H00001"}]}]}

        report = build(blocks, receipt, Path("unused"), Path("unused"),
                       validate=lambda *_: "synthetic", scan_fn=catalog)
        self.assertEqual(report["bag_survey_ids_returned"], ["H00001"])
        self.assertEqual(report["surveyed_depth_cells_confirmed"], 0)
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])


if __name__ == "__main__":
    unittest.main()

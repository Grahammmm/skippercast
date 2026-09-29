import unittest

from shapely.geometry import box, mapping

from research.scripts.audit_monterey_noaa_bag_catalog_gap import build


class MontereyNoaaBagCatalogGapTest(unittest.TestCase):
    def setUp(self):
        self.ids = [f"context-{i:02d}" for i in range(17)]
        self.matrix = {"scope": "monterey-300-source-evidence-review-matrix",
                       "review_order": [{"context_id": ident,
                                         "historical_rockfish_positive_windows": 1 if i < 2 else 0}
                                        for i, ident in enumerate(self.ids)]}
        self.context = {"scope": "generalized-statewide-usgs-hard-bottom-context",
                        "features": [{"properties": {"id": ident},
                                      "geometry": mapping(box(-122 + i * .01, 36, -121.999 + i * .01, 36.001))}
                                     for i, ident in enumerate(self.ids)]}

    def scan(self, sectors, *, add_bag=False):
        self.assertEqual(len(sectors), 17)
        return {"health": {"status": "ok"}, "source_url": "https://example.test/noaa",
                "sectors": [{"sector_id": row["id"], "status": "ok", "raw_sha256": "a" * 64,
                             "surveys": [{"id": "W12345"}] if add_bag and i == 0 else []}
                            for i, row in enumerate(sectors)]}

    def test_no_bag_lead_is_acquisition_triage_only(self):
        result = build(self.matrix, self.context, self.scan)
        self.assertEqual(result["research_outline_count"], 17)
        self.assertEqual(result["historical_rockfish_positive_outline_count"], 2)
        self.assertEqual(result["outlines_with_downloadable_bag_catalog_leads"], 0)
        self.assertFalse(result["depth_uncertainty_gate_satisfied"])
        self.assertFalse(result["exportable"])

    def test_new_bag_lead_requires_review(self):
        with self.assertRaisesRegex(ValueError, "BAG lead appeared"):
            build(self.matrix, self.context, lambda sectors: self.scan(sectors, add_bag=True))


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import unittest

from shapely.geometry import box, GeometryCollection

from scripts.audit_estero_research_blocks import screen, verify_enc
from scripts.check_estero_review_change import compare


ROOT = Path(__file__).resolve().parents[1]


class EsteroResearchBlocksTest(unittest.TestCase):
    def test_whole_block_margin_holds_near_closure(self):
        blocks = {(250, 300, 100, 100): 12, (250, 300, 104, 100): 8}
        coverage = box(9900, 9900, 10600, 10200)
        mpa = box(10150, 10000, 10160, 10100)
        bands, private = screen(blocks, coverage, mpa, GeometryCollection(),
                                coverage, GeometryCollection())
        row = bands["250-300ft"]
        self.assertEqual(row["blocks"], 2)
        self.assertEqual(row["within_mpa_review_margin_blocks"], 1)
        self.assertEqual(row["outside_both_review_margins_cells"], 8)
        self.assertTrue(all(f["properties"]["fishing_target"] is False
                            and f["properties"]["exportable"] is False
                            for f in private["features"]))

    def test_queried_enc_layers_are_required_even_when_empty(self):
        with self.assertRaisesRegex(ValueError, "ENC danger queries are incomplete"):
            verify_enc({"scope_id": "estero-independent-deep-hard-context",
                        "query_receipts": [], "features": []}, None)

    def test_published_receipt_stays_research_only(self):
        report = json.loads((ROOT / "dist/data/estero-2012-depth-class-closure-block-review.json").read_text())
        self.assertEqual(report["scope"], "estero-independent-research-block-closure-screen")
        self.assertEqual(report["bands"]["200-250ft"]["hard_rugose_cells"]
                         + report["bands"]["250-300ft"]["hard_rugose_cells"], 24_210)
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertEqual(report["noaa_enc_query_layers"], 18)
        self.assertEqual(report["noaa_enc_charted_danger_features"], 0)
        self.assertNotIn("features", report)
        self.assertTrue(compare(report, dict(report)))
        changed = json.loads(json.dumps(report))
        changed["official_geometry_sha256"]["cdfw_mpas"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source or screening change"):
            compare(report, changed)


if __name__ == "__main__":
    unittest.main()

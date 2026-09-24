import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_csumb_scc_native import audit


ROOT = Path(__file__).resolve().parents[1]


class CsumbNativeSourceReviewTest(unittest.TestCase):
    def test_original_grid_receipt_stays_out_of_fishing_targets(self):
        report = json.loads((ROOT / "dist/data/csumb-scc-native-source-review.json").read_text())
        self.assertEqual(report["publication_status"], "source-evidence-only")
        self.assertEqual({s["source_id"] for s in report["sources"]},
                         {"csumb-scc-block04", "csumb-scc-block05", "csumb-scc-block06"})
        for source in report["sources"]:
            self.assertEqual(source["native_vertical_datum"], "NAVD88 Geoid09")
            self.assertEqual(source["status"], "held-from-fishing-targets")
            self.assertEqual(source["bathymetry"]["crs"], "EPSG:26910")
            self.assertEqual(source["bathymetry"]["resolution_m"], [2.0, 2.0])
            self.assertGreater(source["bathymetry"]["valid_cells"], 6_000_000)
            self.assertGreater(source["terrain_habitat"]["class_counts"]["-31"], 0)
            self.assertLess(source["bathymetry"]["valid_cell_envelope_wgs84"][2], -121.1)
        self.assertNotIn("targets", report)

    def test_changed_or_incomplete_archive_fails_closed(self):
        specs = json.loads((ROOT / "catalog/csumb-scc-native-sources.json").read_text())["sources"]
        spec = next(source for source in specs if source["survey_id"] == "SCC_Block05")
        with tempfile.TemporaryDirectory() as cache:
            (Path(cache) / "SCC_Block05_additional_products.tar.gz").write_bytes(b"incomplete")
            with self.assertRaisesRegex(ValueError, "byte count changed"):
                audit(spec, Path(cache))


if __name__ == "__main__":
    unittest.main()

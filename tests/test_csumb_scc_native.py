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
        source = report["sources"][0]
        self.assertEqual(source["native_vertical_datum"], "NAVD88 Geoid09")
        self.assertEqual(source["status"], "held-from-fishing-targets")
        self.assertEqual(source["bathymetry"]["crs"], "EPSG:26910")
        self.assertEqual(source["bathymetry"]["resolution_m"], [2.0, 2.0])
        self.assertGreater(source["bathymetry"]["valid_cells"], 6_000_000)
        self.assertGreater(source["terrain_habitat"]["class_counts"]["-31"], 0)
        self.assertNotIn("targets", report)

    def test_changed_or_incomplete_archive_fails_closed(self):
        spec = json.loads((ROOT / "catalog/csumb-scc-native-sources.json").read_text())["sources"][0]
        with tempfile.TemporaryDirectory() as cache:
            (Path(cache) / "SCC_Block05_additional_products.tar.gz").write_bytes(b"incomplete")
            with self.assertRaisesRegex(ValueError, "byte count changed"):
                audit(spec, Path(cache))


if __name__ == "__main__":
    unittest.main()

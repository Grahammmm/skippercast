import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UsgsSourceRegistryDatumTest(unittest.TestCase):
    def test_original_usgs_depth_datum_is_not_invented(self):
        registry = {row["id"]: row for row in json.loads((ROOT / "catalog/sources.json").read_text())["sources"]}
        ledger = json.loads((ROOT / "dist/data/usgs-depth-datum-ledger.json").read_text())
        by_release = {row["id"]: row for row in ledger["sources"]}
        for source_id, release_id in (("usgs-point-buchon", "P9KBGELE"),
                                      ("usgs-morro-bay", "P9HEZNRO"),
                                      ("usgs-point-estero", "P9ZSTUK1")):
            with self.subTest(source=source_id):
                self.assertIsNone(by_release[release_id]["declared_vertical_datum"])
                self.assertIsNone(registry[source_id]["vertical_datum"])
                self.assertTrue(any("per-cell upper uncertainty" in text
                                    for text in registry[source_id]["limitations"]))


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import unittest

from scripts import discover_noaa_multibeam_footprints as discovery


ROOT = Path(__file__).resolve().parents[1]


class NOAAFootprintDiscoveryTests(unittest.TestCase):
    def test_published_receipt_is_complete_and_research_only(self):
        receipt = json.loads((ROOT / "dist/data/noaa-central-multibeam-footprint-leads.json").read_text())
        self.assertEqual(receipt["status"], "complete-catalog-query")
        self.assertEqual({row["sector_id"] for row in receipt["sectors"]}, set(discovery.SECTORS))
        self.assertGreater(receipt["unique_footprint_object_ids"], 0)
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])

    def test_truncated_service_result_fails_instead_of_implying_no_data(self):
        responses = iter([({"count": 2}, "countsha"),
                          ({"features": [{"attributes": {"OBJECTID": 1, "DOWNLOAD_URL": None}}],
                            "exceededTransferLimit": True}, "datasha")])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            discovery.query({"id": "big-sur", "bounds": [-122.2, 35.73, -121.25, 36.31]},
                            lambda _url: next(responses))

    def test_duplicate_feature_fails(self):
        responses = iter([({"count": 2}, "countsha"),
                          ({"features": [{"attributes": {"OBJECTID": 1, "DOWNLOAD_URL": None}},
                                        {"attributes": {"OBJECTID": 1, "DOWNLOAD_URL": None}}]}, "datasha")])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            discovery.query({"id": "big-sur", "bounds": [-122.2, 35.73, -121.25, 36.31]},
                            lambda _url: next(responses))


if __name__ == "__main__":
    unittest.main()

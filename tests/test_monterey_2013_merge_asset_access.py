import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from scripts.audit_monterey_2013_merge_asset_access import DEM_PREFIX, FULL_PREFIX, PREFIXES, audit, parse_listing


ROOT = Path(__file__).resolve().parents[1]


def listing(prefix, keys, truncated=False, token=None):
    contents = "".join(f"<Contents><Key>{key}</Key><Size>3</Size><LastModified>2025-01-01T00:00:00Z</LastModified></Contents>" for key in keys)
    continuation = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    return (f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f'<Prefix>{prefix}</Prefix><KeyCount>{len(keys)}</KeyCount>'
            f'<IsTruncated>{str(truncated).lower()}</IsTruncated>{continuation}{contents}</ListBucketResult>').encode()


class PublishedAssetAccess(unittest.TestCase):
    def test_saved_receipt_does_not_promote_supplemental_files(self):
        saved = json.loads((ROOT / "dist/data/monterey-2013-merge-public-asset-access.json").read_text())
        self.assertEqual([item["prefix"] for item in saved["listings"]], list(PREFIXES))
        self.assertEqual(saved["requested_accuracy_inventory_or_acoustic_assets_found"], [])
        self.assertEqual(saved["full_archive"]["objects"], 16050)
        self.assertEqual(saved["full_archive"]["data_tile_objects"], 8018)
        self.assertEqual(saved["dem_archive"]["objects"], 16132)
        self.assertEqual(saved["dem_archive"]["data_tile_objects"], 8040)
        self.assertFalse(saved["candidate_accuracy_layer_obtained"])
        self.assertFalse(saved["fishing_target"])

    def test_new_accuracy_file_is_detected_for_review(self):
        def fake(url):
            query = parse_qs(urlsplit(url).query)
            prefix = query["prefix"][0]
            keys = [prefix + "Vertical_Accuracy_Layer.zip"] if prefix == DEM_PREFIX else []
            return listing(prefix, keys)
        found = audit(fake)
        self.assertEqual(found["requested_accuracy_inventory_or_acoustic_assets_found"],
                         [DEM_PREFIX + "Vertical_Accuracy_Layer.zip"])
        self.assertFalse(found["candidate_accuracy_layer_obtained"])

    def test_truncated_listing_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "pagination"):
            parse_listing(listing(PREFIXES[0], [], truncated=True, token="page2"), PREFIXES[0])

    def test_full_archive_pagination_detects_later_asset(self):
        def fake(url):
            query = parse_qs(urlsplit(url).query)
            prefix = query["prefix"][0]
            if prefix == FULL_PREFIX and "continuation-token" not in query:
                return listing(prefix, [prefix + "one.copc.laz"], truncated=True, token="page2")
            if prefix == FULL_PREFIX:
                return listing(prefix, [prefix + "acoustic-source-extents.gdb.zip"])
            return listing(prefix, [])
        found = audit(fake)
        self.assertEqual(found["full_archive"]["pages"], 2)
        self.assertEqual(found["requested_accuracy_inventory_or_acoustic_assets_found"],
                         [FULL_PREFIX + "acoustic-source-extents.gdb.zip"])


if __name__ == "__main__":
    unittest.main()

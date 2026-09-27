import json
from pathlib import Path
import unittest

from scripts.audit_monterey_2013_merge_asset_access import PREFIXES, audit, parse_listing


ROOT = Path(__file__).resolve().parents[1]


def listing(prefix, keys, truncated=False):
    contents = "".join(f"<Contents><Key>{key}</Key><Size>3</Size><LastModified>2025-01-01T00:00:00Z</LastModified></Contents>" for key in keys)
    return (f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f'<Prefix>{prefix}</Prefix><KeyCount>{len(keys)}</KeyCount>'
            f'<IsTruncated>{str(truncated).lower()}</IsTruncated>{contents}</ListBucketResult>').encode()


class PublishedAssetAccess(unittest.TestCase):
    def test_saved_receipt_does_not_promote_supplemental_files(self):
        saved = json.loads((ROOT / "dist/data/monterey-2013-merge-public-asset-access.json").read_text())
        self.assertEqual([item["prefix"] for item in saved["listings"]], list(PREFIXES))
        self.assertEqual(saved["requested_accuracy_inventory_or_acoustic_assets_found"], [])
        self.assertFalse(saved["candidate_accuracy_layer_obtained"])
        self.assertFalse(saved["fishing_target"])

    def test_new_accuracy_file_is_detected_for_review(self):
        def fake(url):
            prefix = PREFIXES[0] if "geoid18" in url else PREFIXES[1]
            keys = [prefix + "Vertical_Accuracy_Layer.zip"] if prefix == PREFIXES[0] else []
            return listing(prefix, keys)
        found = audit(fake)
        self.assertEqual(found["requested_accuracy_inventory_or_acoustic_assets_found"],
                         [PREFIXES[0] + "Vertical_Accuracy_Layer.zip"])
        self.assertFalse(found["candidate_accuracy_layer_obtained"])

    def test_truncated_listing_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "pagination"):
            parse_listing(listing(PREFIXES[0], [], truncated=True), PREFIXES[0])


if __name__ == "__main__":
    unittest.main()

"""research/receipts/manifest.json pins the sha256 of every research receipt (P1-02b)."""
import json
import unittest

from research.lib.receipts import MANIFEST, RECEIPTS, manifest_entries


class ReceiptManifestTest(unittest.TestCase):
    def test_manifest_matches_every_receipt(self):
        recorded = json.loads(MANIFEST.read_text())['files']
        actual = manifest_entries(RECEIPTS)
        self.assertEqual(sorted(set(actual) - set(recorded)), [], 'receipt missing from manifest; run python -m research.lib.receipts')
        self.assertEqual(sorted(set(recorded) - set(actual)), [], 'manifest lists a receipt that no longer exists')
        changed = sorted(name for name in actual if actual[name] != recorded[name])
        self.assertEqual(changed, [], 'receipt bytes changed; review, then run python -m research.lib.receipts')


if __name__ == '__main__':
    unittest.main()

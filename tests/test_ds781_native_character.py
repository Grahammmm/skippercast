"""The statewide original-character pass must remain a source review."""
import json
from pathlib import Path
import unittest

from scripts.audit_usgs_ds781_native_character import allowed, signature


ROOT = Path(__file__).resolve().parents[1]


class StatewideCharacterTests(unittest.TestCase):
    def test_original_archive_host_and_path_are_bounded(self):
        self.assertTrue(allowed('https://pubs.usgs.gov/ds/781/DrakesBay/data/SeafloorCharacter_DrakesBay.zip'))
        self.assertTrue(allowed('https://cmgds.marine.usgs.gov/data-releases/media/2023/example.zip'))
        for url in ('http://pubs.usgs.gov/ds/781/test.zip',
                    'https://pubs.usgs.gov.evil.test/ds/781/test.zip',
                    'https://cmgds.marine.usgs.gov/private/test.zip'):
            self.assertFalse(allowed(url))

    def test_statewide_receipt_preserves_held_semantics(self):
        data = json.loads((ROOT / 'dist/data/usgs-ds781-native-character-review.json').read_text())
        self.assertEqual(data['product_count'], 35)
        self.assertEqual((data['inspected_count'], data['held_count'], data['failed_count']), (17, 18, 0))
        self.assertEqual(sum(row.get('class_table_status') == 'verified' for row in data['products']), 10)
        self.assertFalse(data['fishing_target'])
        self.assertFalse(data['exportable'])
        for row in data['products']:
            if row['status'] == 'held':
                self.assertNotIn('class_counts', row)
            elif row['status'] == 'ok':
                self.assertEqual(sum(row['class_counts'].values()), row['valid_pixels'])
                if row['class_table_status'] == 'verified':
                    self.assertEqual(sum(v['count'] for v in row['original_class_table']), row['valid_pixels'])
        altered = dict(data, reviewed_at='later')
        self.assertEqual(signature(data), signature(altered))
        altered['failed_count'] = 1
        self.assertNotEqual(signature(data), signature(altered))


if __name__ == '__main__':
    unittest.main()

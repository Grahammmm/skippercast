import json
from pathlib import Path
import unittest

from scripts.merge_vr_native_depth_reviews import merge


ROOT = Path(__file__).resolve().parents[1]


class MergeNativeDepthReviewTests(unittest.TestCase):
    def setUp(self):
        self.sectors = json.loads((ROOT / 'dist/data/coastal-sectors.json').read_text())
        self.base = json.loads((ROOT / 'dist/data/noaa-vr-native-depth-review.json').read_text())
        self.crescent = json.loads((ROOT / 'dist/data/noaa-h12131-native-depth-review.json').read_text())

    def test_extra_original_survey_changes_del_norte_depth_lead(self):
        result = merge([self.base, self.crescent], self.sectors)
        row = next(row for row in result['sectors'] if row['sector_id'] == 'del-norte')
        self.assertIn('H12131', row['survey_ids_with_eligible_cells'])
        self.assertGreaterEqual(row['depth_uncertainty_eligible_cells'], 453524)
        self.assertEqual(result['survey_file_count'], self.base['survey_file_count'] + 1)
        self.assertFalse(result['fishing_target'])
        self.assertFalse(result['exportable'])

    def test_published_statewide_inventory_includes_all_large_original_reviews(self):
        output = json.loads((ROOT / 'dist/data/noaa-vr-native-depth-expanded-review.json').read_text())
        self.assertEqual(output['survey_file_count'], 35)
        self.assertEqual(output['source_review_count'], 5)
        by_sector = {row['sector_id']: row for row in output['sectors']}
        self.assertEqual(by_sector['del-norte']['survey_ids_with_eligible_cells'],
                         ['H11985', 'H12131'])
        self.assertIn('H11970', by_sector['north-mendocino']['survey_ids_with_eligible_cells'])
        self.assertIn('H11972', by_sector['north-mendocino']['survey_ids_with_eligible_cells'])
        self.assertFalse(output['fishing_target'])
        self.assertFalse(output['exportable'])

    def test_duplicate_or_failed_review_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            merge([self.crescent, self.crescent], self.sectors)
        broken = {**self.crescent, 'status': 'degraded'}
        with self.assertRaisesRegex(ValueError, 'Incomplete or failed'):
            merge([self.base, broken], self.sectors)


if __name__ == '__main__':
    unittest.main()

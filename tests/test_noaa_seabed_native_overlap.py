"""Sparse historical seabed descriptions cannot become unscreened rock targets."""
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NoaaSeabedNativeOverlapTests(unittest.TestCase):
    def test_public_overlap_receipt_is_coordinate_free_and_source_bound(self):
        review = json.loads((ROOT / 'dist/data/noaa-seabed-samples-native-overlap-review.json').read_text())
        samples = json.loads((ROOT / 'dist/data/noaa-seabed-samples-sector-review.json').read_text())
        sectors = json.loads((ROOT / 'dist/data/coastal-sectors.json').read_text())['sectors']
        self.assertEqual(review['scope'], 'nos-rock-description-versus-original-noaa-depth-triage')
        self.assertEqual(review['sample_page_sha256'], samples['page_sha256'])
        self.assertEqual(len(review['sectors']), len(sectors))
        self.assertEqual({row['sector_id'] for row in review['sectors']},
                         {row['id'] for row in sectors})
        self.assertEqual(review['regular_bag_review_sha256'], hashlib.sha256(
            (ROOT / 'dist/data/noaa-regular-native-depth-review.json').read_bytes()).hexdigest())
        self.assertEqual(review['bodega_original_hard_context_sha256'], hashlib.sha256(
            (ROOT / 'dist/data/sf-native-hard-context.geojson').read_bytes()).hexdigest())
        self.assertEqual(sum(row['uncurated_rock_word_samples'] for row in review['sectors']), 18)
        self.assertEqual(sum(row['on_measured_native_cell'] for row in review['sectors']), 1)
        self.assertEqual(sum(row['qualified_outside_mpa_buffer'] for row in review['sectors']), 1)
        self.assertEqual(sum(row['qualified_inside_reviewed_bodega_hard_outline']
                             for row in review['sectors']), 0)
        bodega = next(row for row in review['sectors'] if row['sector_id'] == 'bodega-reyes')
        self.assertEqual(bodega['nearest_reviewed_bodega_hard_outline_m_rounded_100'], 1100)
        self.assertFalse(review['fishing_target'])
        self.assertFalse(review['exportable'])
        public = json.dumps(review)
        for forbidden in ('coordinates', 'longitude', 'latitude', 'OBJECTID', 'SAMPLE'):
            self.assertNotIn(forbidden, public)


if __name__ == '__main__':
    unittest.main()

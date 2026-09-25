"""Aptos original rock classes cannot borrow modeled NOAA chart-depth pixels."""
import json
from pathlib import Path
import unittest

from scripts.screen_usgs_map_nbs_overlap import signature, source_row


ROOT = Path(__file__).resolve().parents[1]
DIGEST = '9fcab31d296bcf75c26c3aa937fe7fff190f0365299b6a287f76e93694dbcead'


class UsgsMapNbsOverlapTests(unittest.TestCase):
    def test_aptos_original_table_supplies_all_rock_depth_slope_codes(self):
        native = json.loads((ROOT / 'dist/data/usgs-offshore-aptos-native-audit.json').read_text())
        row, codes = source_row(native, 'OffshoreAptos', DIGEST)
        self.assertEqual(codes, [3, 13, 53])
        self.assertEqual(row['class_table_status'], 'verified')
        changed = json.loads(json.dumps(native))
        next(item for item in changed['products'] if item['archive_sha256'] == DIGEST)['class_counts']['53'] += 1
        with self.assertRaisesRegex(ValueError, 'counts changed'):
            source_row(changed, 'OffshoreAptos', DIGEST)

    def test_all_intersecting_noaa_tiles_are_measured_depth_failures(self):
        report = json.loads((ROOT / 'dist/data/usgs-offshore-aptos-noaa-mllw-overlap-review.json').read_text())
        self.assertEqual(report['scope'], 'usgs-map-original-rock-versus-noaa-measured-mllw')
        self.assertEqual((report['tile_count'], len(report['tiles'])), (9, 9))
        self.assertEqual(report['original_rugose_rock_values'], [3, 13, 53])
        self.assertTrue(any(item['original_rock_class_pixels_at_tile_centers'] > 0
                            for item in report['tiles']))
        self.assertTrue(all(item['qualified_measured_mllw_pixels'] == 0 and
                            item['strict_measured_rock_overlap_pixels'] == 0 for item in report['tiles']))
        self.assertFalse(report['fishing_target'])
        self.assertFalse(report['exportable'])
        later = json.loads(json.dumps(report))
        later['reviewed_at'] = 'later'
        self.assertEqual(signature(report), signature(later))
        later['tiles'][0]['strict_measured_rock_overlap_pixels'] = 1
        self.assertNotEqual(signature(report), signature(later))


if __name__ == '__main__':
    unittest.main()

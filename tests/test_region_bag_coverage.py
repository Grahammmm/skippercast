"""A neighboring survey cannot be attributed to a region by its survey name."""
import unittest

from scripts.audit_region_bag_coverage import build


class RegionBagCoverageTest(unittest.TestCase):
    def test_geography_and_hold_are_explicit(self):
        def bag(survey, bounds):
            return {'survey_id': survey, 'url': f'https://noaa.example/{survey}.bag',
                    'file_sha256': 'a' * 64, 'status': 'ok', 'raster_bounds_wgs84': bounds,
                    'overview_resolution_m': [1, 1], 'refinement_grids_at_most_4m': 0,
                    'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                    'survey_end': '2009-01-01'}
        audit = {'scope': 'noaa-original-bag-native-overview-audit', 'collected_at': '2026-09-23',
                 'max_bytes': 100000000, 'files': [
                     bag('F00562', [-124.3, 41.7, -124.1, 41.8]),
                     bag('H11981', [-124.2635, 41.2844, -124.0604, 41.4774])]}
        region = {'id': 'crescent-city', 'status': 'draft', 'bounds': [-124.75, 41.55, -124.05, 42]}
        holds = {'scope': 'reviewed-noaa-survey-fishing-lead-holds', 'holds': [
            {'survey_id': 'F00562', 'reason': 'Harbor approach'}]}
        row = build(audit, [region], holds)['regions'][0]
        self.assertEqual([x['survey_id'] for x in row['leads']], ['F00562'])
        self.assertEqual(row['held_bag_bboxes'], 1)
        self.assertEqual(row['unheld_fine_regular_bag_bboxes'], 0)


if __name__ == '__main__':
    unittest.main()

import unittest

from scripts.summarize_native_sector_leads import build


class NativeSectorLeadsTest(unittest.TestCase):
    def test_catalog_survey_outside_sector_does_not_count_as_grid(self):
        audit = {
            'scope': 'noaa-original-bag-native-overview-audit', 'collected_at': '2026-09-23',
            'max_bytes': 100000000, 'file_count': 3, 'inspected_count': 3,
            'health': {'status': 'ok', 'issues': []},
            'files': [
                {'survey_id': 'H1', 'url': 'https://example.org/a.bag', 'status': 'ok',
                 'raster_bounds_wgs84': [-123, 40, -122, 41],
                 'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                 'overview_resolution_m': [2, 2], 'variable_refinement_records': 0},
                {'survey_id': 'H1', 'url': 'https://example.org/b.bag', 'status': 'ok',
                 'raster_bounds_wgs84': [-126, 45, -125, 46],
                 'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                 'overview_resolution_m': [2, 2], 'variable_refinement_records': 0},
                {'survey_id': 'H1', 'url': 'https://example.org/c.bag', 'status': 'ok',
                 'raster_bounds_wgs84': [-123, 40, -122, 41],
                 'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                 'overview_resolution_m': [16, 16], 'variable_refinement_records': 20,
                 'refinement_grids_at_most_4m': 5},
            ],
        }
        discovery = {'scope': 'noaa-bag-survey-discovery', 'collected_at': '2026-09-23',
                     'sectors': [{'sector_id': 'test', 'status': 'ok',
                                  'request_url': 'https://example.org/query?geometry=-124%2C39%2C-121%2C42',
                                  'surveys': [{'id': 'H1'}]}]}
        sectors = {'sectors': [{'id': 'test', 'name': 'Test', 'coast': 'northern'}]}
        overlap = {'scope': 'statewide-native-depth-substrate-overlap-leads',
                   'leads': [{'url': 'https://example.org/a.bag'}]}
        row = build(audit, discovery, sectors, overlap)['sectors'][0]
        self.assertEqual(row['audited_bag_files_associated_with_surveys'], 3)
        self.assertEqual(row['georeferenced_bag_bboxes_intersecting_sector'], 2)
        self.assertEqual(row['substrate_overlap_screen_bboxes'], 1)
        self.assertEqual(row['variable_resolution_4m_refinement_bboxes'], 1)
        self.assertEqual(row['not_in_sector_bbox_count'], 1)

    def test_reviewed_harbor_hold_is_counted_but_not_promotable(self):
        audit = {'scope': 'noaa-original-bag-native-overview-audit', 'collected_at': '2026-09-23',
                 'max_bytes': 100000000, 'file_count': 1, 'inspected_count': 1,
                 'health': {'status': 'ok', 'issues': []}, 'files': [
                     {'survey_id': 'F00562', 'url': 'https://example.org/harbor.bag', 'status': 'ok',
                      'raster_bounds_wgs84': [-124.3, 41.7, -124.1, 41.8],
                      'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                      'overview_resolution_m': [1, 1], 'variable_refinement_records': 0}]}
        discovery = {'scope': 'noaa-bag-survey-discovery', 'collected_at': '2026-09-23',
                     'sectors': [{'sector_id': 'del-norte', 'status': 'ok',
                                  'request_url': 'https://example.org/query?geometry=-124.5%2C41.5%2C-124%2C42',
                                  'surveys': [{'id': 'F00562'}]}]}
        sectors = {'sectors': [{'id': 'del-norte', 'name': 'Del Norte', 'coast': 'northern'}]}
        overlap = {'scope': 'statewide-native-depth-substrate-overlap-leads',
                   'leads': [{'survey_id': 'F00562', 'url': 'https://example.org/harbor.bag',
                              'source_report_url': 'https://data.ngdc.noaa.gov/report.pdf'}]}
        holds = {'schema_version': 1, 'scope': 'reviewed-noaa-survey-fishing-lead-holds',
                 'holds': [{'survey_id': 'F00562', 'disposition': 'withhold_from_fishing_promotion',
                            'reason': 'Original report identifies uncharted approach rocks.',
                            'report_url': 'https://data.ngdc.noaa.gov/report.pdf', 'report_sha256': 'a'*64}]}
        row = build(audit, discovery, sectors, overlap, holds)['sectors'][0]
        self.assertEqual(row['substrate_overlap_screen_bboxes'], 1)
        self.assertEqual(row['held_survey_ids'], ['F00562'])
        self.assertEqual(row['eligible_for_native_substrate_review_bboxes'], 0)


if __name__ == '__main__':
    unittest.main()

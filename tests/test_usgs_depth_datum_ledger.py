import unittest

from scripts.build_usgs_depth_datum_ledger import build


def fixture():
    record = {'kind': 'bathymetry', 'status': 'ok', 'metadata_url': 'https://pubs.usgs.gov/example.xml',
              'xml_sha256': 'a' * 64, 'bounds': {'westbc': -123, 'southbc': 37, 'eastbc': -122, 'northbc': 38},
              'native_vertical_datum_declared': None, 'native_vertical_datum_code': None,
              'vertical_datum_evidence': 'unverified-text-mentions', 'vertical_datum_mentions': ['NAVD88']}
    source = {'kind': 'bathymetry', 'status': 'ok', 'block_id': 'Test',
              'metadata_url': record['metadata_url'], 'metadata_sha256': record['xml_sha256'],
              'archive_url': 'https://pubs.usgs.gov/example.zip', 'archive_sha256': 'b' * 64,
              'raster_bounds_wgs84': [-122.8, 37.2, -122.7, 37.3],
              'native_resolution': [2, 2], 'valid_pixels': 100}
    metadata = [{'scope': 'usgs-state-waters-native-metadata', 'health': {'status': 'ok'},
                 'records': [record]},
                {'scope': 'usgs-state-waters-doi-native-metadata', 'health': {'status': 'ok'},
                 'records': []}]
    audits = [{'scope': 'usgs-state-waters-native-grid-audit', 'health': {'status': 'ok'},
               'products': [source]},
              {'scope': 'usgs-state-waters-doi-native-grid-audit', 'health': {'status': 'ok'},
               'products': []}]
    sectors = {'sectors': [{'id': str(i), 'name': str(i), 'coast': 'san-francisco'} for i in range(19)]}
    discovery = {'scope': 'noaa-bag-survey-discovery', 'health': {'status': 'ok'},
                 'sectors': [{'sector_id': str(i), 'status': 'ok',
                              'request_url': f'https://example.test/query?geometry={-123 if i == 0 else -120},37,{-122 if i == 0 else -119},38'}
                             for i in range(19)]}
    return metadata, audits, discovery, sectors


class OriginalDatumLedgerTests(unittest.TestCase):
    def test_free_text_datum_is_not_promoted_to_fishing_depth(self):
        result = build(*fixture())
        self.assertEqual(result['sectors'][0]['source_grid_bbox_count'], 1)
        self.assertEqual(result['sectors'][1]['source_grid_bbox_count'], 0)
        self.assertIsNone(result['sources'][0]['structured_vertical_datum_code'])
        self.assertFalse(result['sources'][0]['depth_qualified_for_fishing'])

    def test_changed_xml_hash_stops_source_promotion(self):
        metadata, audits, discovery, sectors = fixture()
        audits[0]['products'][0]['metadata_sha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
            build(metadata, audits, discovery, sectors)


if __name__ == '__main__':
    unittest.main()

"""NCEI source discovery must fail closed on partial ArcGIS responses."""
import json
from pathlib import Path
import unittest

from scripts.discover_ncei_multibeam import collect, collect_sector, normalize_feature, validate_config, validate_service


ROOT = Path(__file__).resolve().parents[1]


class NCEIMultibeamDiscovery(unittest.TestCase):
    def test_all_sector_searches_match_the_reviewed_latitude_partitions(self):
        config = json.loads((ROOT / 'catalog/ncei-multibeam-search.json').read_text())
        sectors = json.loads((ROOT / 'catalog/coastal-sectors.json').read_text())
        validate_config(config, sectors)
        bad = json.loads(json.dumps(config))
        bad['searches'][0]['bbox_wgs84'][1] += .01
        with self.assertRaises(ValueError):
            validate_config(bad, sectors)

    def test_service_schema_cannot_silently_lose_original_identity(self):
        fields = ('OBJECTID', 'SURVEY_ID', 'PLATFORM', 'SURVEY_YEAR', 'SOURCE', 'NGDC_ID',
                  'DOWNLOAD_URL', 'START_TIME', 'END_TIME', 'INSTRUMENT', 'FILE_COUNT')
        row = {'name': 'Multibeam Bathymetric Surveys', 'geometryType': 'esriGeometryPolyline',
               'fields': [{'name': key} for key in fields],
               'advancedQueryCapabilities': {'supportsPagination': True}}
        validate_service(row)
        row['fields'] = [f for f in row['fields'] if f['name'] != 'DOWNLOAD_URL']
        with self.assertRaises(ValueError):
            validate_service(row)

    def test_count_ids_and_feature_batches_must_agree(self):
        entry = {'sector_id': 'big-sur', 'bbox_wgs84': [-122.3, 35.9, -121.5, 36.3]}
        def get(_url, params):
            if params.get('returnCountOnly'):
                return {'count': 2}
            if params.get('returnIdsOnly'):
                return {'objectIds': [7, 9]}
            return {'features': [{'attributes': {'OBJECTID': n, 'SURVEY_ID': f'S{n}',
                                                'DOWNLOAD_URL': f'https://www.ngdc.noaa.gov/ships/S{n}.html'}}
                                 for n in [7, 9]]}
        self.assertEqual(collect_sector(entry, get=get)['trackline_matches'], 2)
        def missing(_url, params):
            if params.get('returnIdsOnly'):
                return {'objectIds': [7]}
            return get(_url, params)
        with self.assertRaises(ValueError):
            collect_sector(entry, get=missing)
        def truncated(_url, params):
            if 'objectIds' in params:
                return {'exceededTransferLimit': True, 'features': []}
            return get(_url, params)
        with self.assertRaises(ValueError):
            collect_sector(entry, get=truncated)

    def test_original_survey_link_must_remain_on_secure_noaa_host(self):
        row = {'attributes': {'OBJECTID': 7, 'SURVEY_ID': 'BSS_Block10',
                              'DOWNLOAD_URL': 'https://www.ngdc.noaa.gov/ships/survey.html'}}
        self.assertEqual(normalize_feature(row)['survey_id'], 'BSS_Block10')
        for link in ('http://www.ngdc.noaa.gov/ships/survey.html',
                     'https://www.ngdc.noaa.gov.evil.example/survey.html'):
            row['attributes']['DOWNLOAD_URL'] = link
            with self.assertRaises(ValueError):
                normalize_feature(row)

    def test_cross_sector_survey_metadata_is_stored_only_once(self):
        config = json.loads((ROOT / 'catalog/ncei-multibeam-search.json').read_text())
        sectors = json.loads((ROOT / 'catalog/coastal-sectors.json').read_text())
        fields = ('OBJECTID', 'SURVEY_ID', 'PLATFORM', 'SURVEY_YEAR', 'SOURCE', 'NGDC_ID',
                  'DOWNLOAD_URL', 'START_TIME', 'END_TIME', 'INSTRUMENT', 'FILE_COUNT')
        def get(_url, params):
            if params.get('f') == 'pjson':
                return {'name': 'Multibeam Bathymetric Surveys', 'geometryType': 'esriGeometryPolyline',
                        'fields': [{'name': key} for key in fields],
                        'advancedQueryCapabilities': {'supportsPagination': True}}
            if params.get('returnCountOnly'):
                return {'count': 1}
            if params.get('returnIdsOnly'):
                return {'objectIds': [7]}
            return {'features': [{'attributes': {'OBJECTID': 7, 'SURVEY_ID': 'Shared'}}]}
        result = collect(config, sectors, get=get)
        self.assertEqual(len(result['sectors']), 19)
        self.assertEqual(result['total_sector_associations'], 19)
        self.assertEqual(result['unique_survey_object_ids'], 1)
        self.assertEqual(len(result['survey_catalog']), 1)
        self.assertEqual(result['sectors'][0]['survey_object_ids'], [7])


if __name__ == '__main__':
    unittest.main()

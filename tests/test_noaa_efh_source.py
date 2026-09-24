"""NOAA EFH is coastwide context, never a site-level bite or legal source."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_noaa_efh_source import FIELDS, audit


ROOT = Path(__file__).resolve().parents[1]


class EfhSourceTests(unittest.TestCase):
    def test_published_receipt_withholds_fishing_and_records_source_mismatch(self):
        item = json.loads((ROOT / 'dist/data/noaa-efh-source-review.json').read_text())
        self.assertFalse(item['fishing_target'])
        self.assertFalse(item['exportable'])
        self.assertFalse(item['legal_clearance'])
        self.assertTrue(item['bluefin_label_needs_2026_crosswalk'])
        self.assertTrue(item['groundfish_is_aggregate_not_rockfish_or_lingcod'])
        self.assertEqual(item['service_label_count'], len(item['service_labels']))
        self.assertTrue(all(len(item[key]) == 64 for key in
                            ('service_sha256', 'layer_sha256', 'distinct_query_sha256')))

    def test_audit_rejects_missing_species_or_changed_field_schema(self):
        service = {'mapName': 'EFH_mapservice'}
        layer = {'id': 4, 'geometryType': 'esriGeometryPolygon',
                 'fields': [{'name': name} for name in FIELDS]}
        query = {'features': [{'attributes': {'SITENAME_L': label}} for label in
                              ('Groundfish', 'Yellowfin Tuna', 'Albacore Tuna')]}
        hashes = {key: 'a' * 64 for key in ('service', 'layer', 'query')}
        result = audit(service, layer, query, hashes, checked_at='2026-09-24T00:00:00Z')
        self.assertFalse(result['fishing_target'])
        del layer['fields'][0]
        with self.assertRaises(ValueError):
            audit(service, layer, query, hashes)
        layer['fields'] = [{'name': name} for name in FIELDS]
        query['features'] = []
        with self.assertRaises(ValueError):
            audit(service, layer, query, hashes)


if __name__ == '__main__':
    unittest.main()

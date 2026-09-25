"""FGDC metadata cannot silently become a fishing-depth or reuse decision."""
import json
from pathlib import Path
import unittest

from scripts.audit_usgs_ds781_metadata import parse_xml, signature, xml_sibling


ROOT = Path(__file__).resolve().parents[1]


class UsgsDs781MetadataTests(unittest.TestCase):
    def test_original_metadata_triage_is_complete_or_explicitly_held(self):
        data = json.loads((ROOT / 'catalog/usgs-ds781-metadata-review.json').read_text())
        self.assertEqual(data['record_count'], len(data['records']))
        self.assertEqual(data['record_count'], 75)
        self.assertEqual(sum(row['status'] == 'reviewed' for row in data['records']), 72)
        self.assertEqual(sum(row['status'] == 'missing-metadata-link' for row in data['records']), 3)
        self.assertFalse(any(row.get('fishing_target') or row.get('exportable') for row in data['records']))
        arcata = next(row for row in data['records'] if row['map_area'] == 'Offshore of Arcata'
                      and row['kind'] == 'bathymetry')
        self.assertEqual(arcata['vertical_datum_declared'], 'instantaneous sea level')
        self.assertEqual(arcata['horizontal_spacing_in_metadata'], [10.0])
        self.assertEqual(arcata['rights_evidence'], 'explicit-public-domain-redistribution')
        eel = [row for row in data['records'] if row['map_area'] == 'Offshore of Eel River']
        self.assertTrue(eel and all(row['status'] == 'missing-metadata-link' for row in eel))

    def test_xml_sibling_and_rights_require_explicit_source_words(self):
        self.assertEqual(xml_sibling('https://pubs.usgs.gov/x_metadata.txt'),
                         'https://pubs.usgs.gov/x_metadata.xml')
        template = '''<metadata><idinfo><citation><citeinfo><title>Original grid</title></citeinfo></citation>
        <useconst>{}</useconst></idinfo><spref><horizsys><planar><planci><coordrep>
        <absres>2.0, 5.0</absres></coordrep><plandu>Meters</plandu></planci></planar></horizsys>
        <vertdef><altsys><altdatum>NAVD88</altdatum></altsys></vertdef></spref></metadata>'''
        ambiguous = parse_xml(template.format('public domain').encode())
        self.assertEqual(ambiguous['rights_evidence'], 'requires-review')
        self.assertEqual(ambiguous['horizontal_spacing_in_metadata'], [2.0, 5.0])
        explicit = parse_xml(template.format('public domain and freely redistributable').encode())
        self.assertEqual(explicit['rights_evidence'], 'explicit-public-domain-redistribution')
        self.assertEqual(explicit['vertical_datum_declared'], 'NAVD88')

    def test_signature_detects_changed_metadata_but_ignores_retrieval_time(self):
        data = json.loads((ROOT / 'catalog/usgs-ds781-metadata-review.json').read_text())
        later = json.loads(json.dumps(data))
        later['reviewed_at'] = 'later'
        self.assertEqual(signature(data), signature(later))
        later['records'][0]['metadata_sha256'] = 'changed'
        self.assertNotEqual(signature(data), signature(later))


if __name__ == '__main__':
    unittest.main()

import hashlib
import unittest

from scripts.audit_usgs_character_semantics import audit, definitions, metadata_formula_for_class3


ENUMERATED = b'''<metadata><eainfo><detailed><attr><attrlabl>Value</attrlabl>
<attrdomv><edom><edomv>3</edomv><edomvd>hard and rugose boulder and bedrock seafloor</edomvd></edom></attrdomv>
</attr></detailed></eainfo></metadata>'''
FORMULA = b'''<metadata><eainfo><detailed><attr><attrlabl>VALUE</attrlabl>
<attrdef>Depth Zone 2, add 0 to grid value; Slope Class 1, add 0 to grid value</attrdef></attr>
<attr><attrlabl>SUBSTRATE</attrlabl><attrdef>Class 3, Rock and boulder, rugose</attrdef></attr>
</detailed></eainfo></metadata>'''


def inputs(xml, *, class_table_status='missing-original-value-table', table=None):
    url = 'https://cmgds.marine.usgs.gov/data/csmp/test.xml'
    digest = hashlib.sha256(xml).hexdigest()
    native = {'scope': 'usgs-ds781-statewide-original-character-raster-audit',
              'inspected_count': 1, 'products': [{
                  'status': 'ok', 'map_area': 'Test area', 'archive_url': 'https://pubs.usgs.gov/test.zip',
                  'archive_sha256': 'archive-digest', 'metadata_url': url,
                  'metadata_sha256': digest, 'class_table_status': class_table_status,
                  'class_counts': {'3': 1}, 'original_class_table': table}]}
    metadata = {'scope': 'usgs-ds781-original-fgdc-metadata-triage', 'records': [{
        'xml_url': url, 'status': 'reviewed', 'rights_evidence': 'explicit-public-domain-redistribution',
        'metadata_sha256': digest}]}
    return native, metadata


class CharacterSemanticsTests(unittest.TestCase):
    def test_enumerated_class_and_formula_are_distinct_original_evidence(self):
        self.assertIn('boulder', definitions(ENUMERATED)['3'])
        self.assertIsNone(metadata_formula_for_class3(ENUMERATED))
        self.assertEqual({}, definitions(FORMULA))
        self.assertIn('rock', metadata_formula_for_class3(FORMULA))
        for raw, expected in ((ENUMERATED, 'fgdc-enumeration'), (FORMULA, 'fgdc-zone-slope-formula')):
            native, metadata = inputs(raw)
            row = audit(native, metadata, getter=lambda _: raw)['products'][0]
            self.assertEqual('verified', row['status'])
            self.assertEqual(expected, row['class_3_verification_source'])

    def test_changed_metadata_and_unreviewed_rights_fail_closed(self):
        native, metadata = inputs(ENUMERATED)
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            audit(native, metadata, getter=lambda _: FORMULA)
        metadata['records'][0]['rights_evidence'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            audit(native, metadata, getter=lambda _: ENUMERATED)

    def test_rock_description_without_zone_formula_is_held(self):
        raw = FORMULA.replace(b'Depth Zone 2, add 0', b'Depth Zone 2, add 10')
        native, metadata = inputs(raw)
        row = audit(native, metadata, getter=lambda _: raw)['products'][0]
        self.assertEqual('held-class-meaning', row['status'])
        self.assertFalse(row['class_3_hard_rugose_verified'])

    def test_verified_original_value_table_can_supply_missing_fgdc_enumeration(self):
        raw = b'<metadata/>'
        table = [{'value': 3, 'substrate_class': 3,
                  'substrate_description': 'Rock and boulders, rugose'}]
        native, metadata = inputs(raw, class_table_status='verified', table=table)
        row = audit(native, metadata, getter=lambda _: raw)['products'][0]
        self.assertEqual('original-raster-value-table', row['class_3_verification_source'])


if __name__ == '__main__':
    unittest.main()

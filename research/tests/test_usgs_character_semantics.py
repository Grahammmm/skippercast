import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from research.scripts import audit_usgs_ds781_metadata as metadata_audit
from research.scripts.audit_usgs_character_semantics import audit, definitions, metadata_formula_for_class3


ENUMERATED = b'''<metadata><eainfo><detailed><attr><attrlabl>Value</attrlabl>
<attrdomv><edom><edomv>3</edomv><edomvd>hard and rugose boulder and bedrock seafloor</edomvd></edom></attrdomv>
</attr></detailed></eainfo></metadata>'''
FORMULA = b'''<metadata><eainfo><detailed><attr><attrlabl>VALUE</attrlabl>
<attrdef>Depth Zone 2, add 0 to grid value; Slope Class 1, add 0 to grid value</attrdef></attr>
<attr><attrlabl>SUBSTRATE</attrlabl><attrdef>Class 3, Rock and boulder, rugose</attrdef></attr>
</detailed></eainfo></metadata>'''
TERMS = ('USGS-authored or produced data and information are in the public domain from the U.S. '
         'Government and are freely redistributable with proper metadata and source attribution. '
         'Please recognize and acknowledge the U.S. Geological Survey as the originator of the dataset '
         'and in products derived from these data.')


class CharacterSemanticsTests(unittest.TestCase):
    def test_standalone_help_from_repository_root(self):
        root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        result = subprocess.run(
            [sys.executable, 'research/scripts/audit_usgs_character_semantics.py', '--help'],
            cwd=root, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('usage:', result.stdout)

    def inputs(self, xml, *, class_table_status='missing-original-value-table', table=None):
        idinfo = f'<idinfo><useconst>{TERMS}</useconst></idinfo>'.encode()
        raw = xml.replace(b'<metadata>', b'<metadata>' + idinfo)
        url = 'https://cmgds.marine.usgs.gov/data/csmp/test.xml'
        archive = 'https://pubs.usgs.gov/test.zip'
        digest = hashlib.sha256(raw).hexdigest()
        native = {'scope': 'usgs-ds781-statewide-original-character-raster-audit',
                  'inspected_count': 1, 'products': [{
                      'status': 'ok', 'map_area': 'Test area', 'archive_url': archive,
                      'archive_sha256': 'archive-digest', 'metadata_url': url,
                      'metadata_sha256': digest, 'class_table_status': class_table_status,
                      'class_counts': {'3': 1}, 'original_class_table': table}]}
        metadata = {'scope': 'usgs-ds781-original-fgdc-metadata-triage', 'record_count': 1, 'records': [{
            'archive_url': archive, 'map_area': 'Test area', 'kind': 'seafloor-character', 'metadata_url': url,
            'xml_url': url, 'status': 'reviewed', 'rights_evidence': 'explicit-public-domain-redistribution',
            'metadata_sha256': digest, 'access_constraints': None, 'use_constraints': TERMS}]}
        review = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'review.json'
        review.write_text(json.dumps(metadata), encoding='utf-8')
        self.enterContext(patch.object(metadata_audit, 'METADATA_REVIEW', review))
        return native, metadata, raw

    def test_enumerated_class_and_formula_are_distinct_original_evidence(self):
        self.assertIn('boulder', definitions(ENUMERATED)['3'])
        self.assertIsNone(metadata_formula_for_class3(ENUMERATED))
        self.assertEqual({}, definitions(FORMULA))
        self.assertIn('rock', metadata_formula_for_class3(FORMULA))
        for xml, expected in ((ENUMERATED, 'fgdc-enumeration'), (FORMULA, 'fgdc-zone-slope-formula')):
            native, metadata, raw = self.inputs(xml)
            row = audit(native, metadata, getter=lambda _: raw)['products'][0]
            self.assertEqual('verified', row['status'])
            self.assertEqual(expected, row['class_3_verification_source'])

    def test_changed_metadata_and_unreviewed_rights_fail_closed(self):
        native, metadata, raw = self.inputs(ENUMERATED)
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            audit(native, metadata, getter=lambda _: FORMULA)
        metadata['records'][0]['rights_evidence'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            audit(native, metadata, getter=lambda _: raw)

    def test_rock_description_without_zone_formula_is_held(self):
        xml = FORMULA.replace(b'Depth Zone 2, add 0', b'Depth Zone 2, add 10')
        native, metadata, raw = self.inputs(xml)
        row = audit(native, metadata, getter=lambda _: raw)['products'][0]
        self.assertEqual('held-class-meaning', row['status'])
        self.assertFalse(row['class_3_hard_rugose_verified'])

    def test_verified_original_value_table_can_supply_missing_fgdc_enumeration(self):
        table = [{'value': 3, 'substrate_class': 3,
                  'substrate_description': 'Rock and boulders, rugose'}]
        native, metadata, raw = self.inputs(b'<metadata></metadata>', class_table_status='verified', table=table)
        row = audit(native, metadata, getter=lambda _: raw)['products'][0]
        self.assertEqual('original-raster-value-table', row['class_3_verification_source'])


if __name__ == '__main__':
    unittest.main()

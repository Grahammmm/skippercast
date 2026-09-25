import json
import hashlib
from pathlib import Path
import unittest

from scripts.audit_usgs_morro_report_datum import audit


ROOT = Path(__file__).resolve().parents[1]


class MorroReportDatumTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'catalog/usgs-morro-report-datum-source.json').read_text())
        self.raw = (b'<html><body>Depth, as referred to in this report, is relative to mean lower low water (MLLW) from verified tides. '
                    b'Bathymetry, backscatter intensity, and benthic habitat offshore of Morro Bay '
                    b'Bathymetry, backscatter intensity, and benthic habitat offshore of Point Estero '
                    b'Bathymetry, backscatter intensity, and benthic habitat offshore of Point Buchon</body></html>')
        self.manifest['report_sha256'] = hashlib.sha256(self.raw).hexdigest()
        self.ledger = json.loads((ROOT / 'dist/data/usgs-depth-datum-ledger.json').read_text())
        self.xml = {ident: (b'<metadata><vertaccr>Estimated to be no less than 20 cm owing to total propagated uncertainties.</vertaccr>'
                            b'<horizpar>Accuracies of final products may be lower.</horizpar></metadata>')
                    for ident in self.manifest['release_ids']}
        for source in self.ledger['sources']:
            if source['id'] in self.xml:
                source['metadata_sha256'] = hashlib.sha256(self.xml[source['id']]).hexdigest()

    def test_report_level_datum_does_not_promote_original_tiffs(self):
        result = audit(self.manifest, self.raw, self.ledger, self.xml)
        self.assertEqual(result['report_depth_reference'], 'MLLW')
        self.assertEqual(len(result['sources']), 3)
        self.assertTrue(all(row['original_tiff_declared_vertical_datum'] is None
                            for row in result['sources']))
        self.assertTrue(all(row['depth_qualified_for_fishing'] is False
                            for row in result['sources']))
        self.assertTrue(all(row['vertical_accuracy_lower_bound_m'] == .2 and
                            row['vertical_accuracy_upper_bound_m'] is None
                            for row in result['sources']))
        self.assertFalse(result['fishing_target'])
        self.assertFalse(result['exportable'])

    def test_changed_report_and_missing_release_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'content changed'):
            audit(self.manifest, self.raw + b'changed', self.ledger, self.xml)
        missing = {**self.ledger, 'sources': [row for row in self.ledger['sources']
                                               if row['id'] != 'P9HEZNRO']}
        with self.assertRaisesRegex(ValueError, 'not fully audited'):
            audit(self.manifest, self.raw, missing, self.xml)
        with self.assertRaisesRegex(ValueError, 'product XML changed'):
            audit(self.manifest, self.raw, self.ledger,
                  {**self.xml, 'P9HEZNRO': self.xml['P9HEZNRO'] + b'changed'})


if __name__ == '__main__':
    unittest.main()

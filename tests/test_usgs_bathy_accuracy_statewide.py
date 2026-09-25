import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_usgs_bathy_accuracy_statewide import build, inspect


ROOT = Path(__file__).resolve().parents[1]


class UsgsAccuracyAuditTests(unittest.TestCase):
    def setUp(self):
        self.ledger = json.loads((ROOT / 'dist/data/usgs-depth-datum-ledger.json').read_text())
        self.source = dict(next(row for row in self.ledger['sources'] if row['id'] == 'P9HEZNRO'))
        self.raw = (b'<metadata><vertaccr>Estimated to be no less than 20 cm, owing to total propagated uncertainties.</vertaccr></metadata>')
        self.source['metadata_sha256'] = hashlib.sha256(self.raw).hexdigest()

    def test_accuracy_floor_stays_narrative_and_non_target(self):
        row = inspect(self.source, self.raw)
        self.assertEqual(row['accuracy_evidence'], 'narrative_only')
        self.assertIn('no less than 20 cm', row['vertical_accuracy_statement'])
        self.assertEqual(row['vertical_accuracy_values'], [])
        self.assertFalse(row['depth_qualified_for_fishing'])
        with self.assertRaisesRegex(ValueError, 'differs from pinned'):
            inspect(self.source, self.raw + b'changed')

    def test_missing_original_xml_is_degraded(self):
        ledger = {**self.ledger, 'sources': [self.source], 'source_grid_count': 1}
        with TemporaryDirectory() as directory:
            result = build(ledger, Path(directory))
        self.assertEqual(result['status'], 'degraded')
        self.assertEqual(result['fully_verified_source_count'], 0)
        self.assertFalse(result['fishing_target'])
        self.assertFalse(result['exportable'])


if __name__ == '__main__':
    unittest.main()

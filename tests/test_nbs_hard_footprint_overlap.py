import json
from pathlib import Path
import unittest

from scripts.audit_nbs_modeling_tile import sha256


ROOT = Path(__file__).resolve().parents[1]


class HardFootprintOverlapTest(unittest.TestCase):
    def test_published_receipts_are_complete_and_non_target(self):
        source = ROOT / 'dist/data'
        inventory = json.loads((source / 'nbs-hard-footprint-tile-inventory.json').read_text())
        depth = json.loads((source / 'nbs-hard-footprint-depth-audit.json').read_text())
        originals = json.loads((source / 'nbs-hard-footprint-usgs-class-fetch.json').read_text())
        overlap = json.loads((source / 'nbs-hard-footprint-original-class-overlap.json').read_text())
        self.assertEqual((inventory['tile_count'], depth['completed_tiles'], depth['failed_tiles']),
                         (102, 102, 0))
        self.assertEqual((originals['requested'], originals['verified'], originals['failed']), (34, 34, 0))
        self.assertEqual(depth['inventory_sha256'], sha256(source / 'nbs-hard-footprint-tile-inventory.json'))
        self.assertEqual(overlap['depth_audit_sha256'], sha256(source / 'nbs-hard-footprint-depth-audit.json'))
        self.assertEqual(sum(coast['tile_count'] for coast in overlap['coasts']), 106)
        for report in (inventory, depth, originals, overlap):
            self.assertFalse(report['fishing_target'])
            self.assertFalse(report['exportable'])
        for coast in overlap['coasts']:
            for sector in coast['source_review']['sectors']:
                for tile in sector['tiles']:
                    self.assertEqual(tile['original_class_releases_not_audited'], [])

    def test_strict_uncertainty_does_not_inherit_2m_sensitivity(self):
        review = json.loads((ROOT / 'dist/data/nbs-hard-footprint-original-class-overlap.json').read_text())
        central = next(coast for coast in review['coasts'] if coast['coast_id'] == 'central')
        sector = next(row for row in central['source_review']['sectors']
                      if row['sector_id'] == 'cambria-morro')
        self.assertEqual(sum(tile['strict_1m_original_class3_unique_pixels'] for tile in sector['tiles']), 0)
        self.assertGreater(sum(tile['sensitivity_2m_original_class3_unique_pixels']
                               for tile in sector['tiles']), 800_000)


if __name__ == '__main__':
    unittest.main()

"""Monterey Bay preview gates: local MPAs, legal scope, no invented targets."""
import json
from pathlib import Path
import unittest

from scripts.prepare_regional_mpas import validate_response
from skippercast.pipeline.settings import settings


ROOT = Path(__file__).resolve().parents[1]
RID = 'santa-cruz-monterey-bay'


class SantaCruzRegionTests(unittest.TestCase):
    def test_twelve_original_cdfw_mpas_are_bound_to_region(self):
        region = json.loads((ROOT / 'regions' / RID / 'region.json').read_text())
        snapshot = json.loads((ROOT / 'dist' / region['assets']['protected_areas']).read_text())
        self.assertEqual(snapshot['region_id'], RID)
        validate_response(snapshot, region['mpa']['bounds'], 12)
        self.assertEqual({f['properties']['NAME'] for f in snapshot['features']}, {
            'Natural Bridges SMR', 'Elkhorn Slough SMR', 'Elkhorn Slough SMCA',
            'Moro Cojo Slough SMR', 'Soquel Canyon SMCA', 'Portuguese Ledge SMCA',
            'Greyhound Rock SMCA', 'Año Nuevo SMR', 'Edward F. Ricketts SMCA',
            'Lovers Point - Julia Platt SMR', 'Pacific Grove Marine Gardens SMCA',
            'Asilomar SMR',
        })

    def test_preview_does_not_export_unqualified_bathymetry(self):
        region = json.loads((ROOT / 'regions' / RID / 'region.json').read_text())
        atlas = json.loads((ROOT / 'dist' / region['assets']['atlas']).read_text())
        self.assertEqual(region['status'], 'preview')
        self.assertEqual(atlas['region_id'], RID)
        self.assertEqual(atlas['targets'], [])
        self.assertEqual(atlas['areas'], [])
        self.assertEqual(atlas['drifts'], [])
        self.assertEqual(region['coverage']['bathymetry']['status'], 'research')

    def test_local_rules_exclude_unrelated_vandenberg_watch(self):
        config = settings(RID)
        rules = config['regulations']
        decision = json.loads((ROOT / rules['review_record']).read_text())
        self.assertEqual(decision['rules_content_sha256'], rules['approved_rules_content_sha256'])
        self.assertIn({'id': RID, 'fishing_bounds': config['region']['fishing_bounds']},
                      decision['reviewed_regions'])
        self.assertIn('mpa-soquel-canyon', config['watches'])
        self.assertIn('mpa-portuguese-ledge', config['watches'])
        self.assertNotIn('mpa-piedras', config['watches'])
        self.assertNotIn('access-vandenberg-maritime', config['watches'])


if __name__ == '__main__':
    unittest.main()

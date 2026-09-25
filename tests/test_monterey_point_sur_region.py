"""Monterey–Point Sur preview must exclude protected areas and unqualified marks."""
import json
from pathlib import Path
import unittest

from scripts.prepare_regional_mpas import validate_response
from skippercast.pipeline.settings import settings


ROOT = Path(__file__).resolve().parents[1]
RID = 'monterey-point-sur'


class MontereyPointSurRegionTests(unittest.TestCase):
    def test_local_cdfw_exclusions_and_no_unqualified_marks(self):
        region = json.loads((ROOT / 'regions' / RID / 'region.json').read_text())
        protected = json.loads((ROOT / 'dist' / region['assets']['protected_areas']).read_text())
        names = {feature['properties']['NAME'] for feature in protected['features']}
        validate_response(protected, region['mpa']['bounds'], 9)
        self.assertEqual(names, {
            'Carmel Pinnacles SMR', 'Carmel Bay SMCA', 'Point Lobos SMR',
            'Point Lobos SMCA', 'Point Sur SMR', 'Point Sur SMCA',
            'Edward F. Ricketts SMCA', 'Lovers Point - Julia Platt SMR',
            'Asilomar SMR',
        })
        atlas = json.loads((ROOT / 'dist' / region['assets']['atlas']).read_text())
        self.assertEqual(region['status'], 'preview')
        self.assertEqual(atlas['region_id'], RID)
        self.assertEqual([atlas[key] for key in ('targets', 'areas', 'drifts')], [[], [], []])

    def test_local_rules_do_not_require_distant_access_pages(self):
        config = settings(RID)
        rules = config['regulations']
        decision = json.loads((ROOT / rules['review_record']).read_text())
        self.assertEqual(decision['rules_content_sha256'], rules['approved_rules_content_sha256'])
        self.assertIn({'id': RID, 'fishing_bounds': config['region']['fishing_bounds']},
                      decision['reviewed_regions'])
        self.assertIn('mpa-point-sur', config['watches'])
        self.assertIn('mpa-carmel-bay', config['watches'])
        self.assertNotIn('access-vandenberg-maritime', config['watches'])
        self.assertNotIn('mpa-piedras', config['watches'])


if __name__ == '__main__':
    unittest.main()

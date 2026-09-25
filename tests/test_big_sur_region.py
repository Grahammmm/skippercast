"""Big Sur previews cannot turn MPA habitat or coarse sediment into fishing marks."""
import json
from pathlib import Path
import unittest

from scripts.prepare_regional_mpas import validate_response
from skippercast.pipeline.settings import settings


ROOT = Path(__file__).resolve().parents[1]
RID = 'big-sur-coast'


class BigSurRegionTests(unittest.TestCase):
    def test_protected_geometry_and_unqualified_export_gate(self):
        region = json.loads((ROOT / 'regions' / RID / 'region.json').read_text())
        protected = json.loads((ROOT / 'dist' / region['assets']['protected_areas']).read_text())
        validate_response(protected, region['mpa']['bounds'], 4)
        self.assertEqual({f['properties']['NAME'] for f in protected['features']}, {
            'Point Sur SMR', 'Point Sur SMCA', 'Big Creek SMR', 'Big Creek SMCA',
        })
        atlas = json.loads((ROOT / 'dist' / region['assets']['atlas']).read_text())
        self.assertEqual(region['status'], 'preview')
        self.assertEqual(atlas['region_id'], RID)
        self.assertEqual([atlas[key] for key in ('targets', 'areas', 'drifts')], [[], [], []])
        self.assertEqual(region['coverage']['bathymetry']['status'], 'research')

    def test_big_creek_access_is_scoped_to_this_coast(self):
        config = settings(RID)
        decision = json.loads((ROOT / config['regulations']['review_record']).read_text())
        self.assertIn({'id': RID, 'fishing_bounds': config['region']['fishing_bounds']},
                      decision['reviewed_regions'])
        self.assertIn('mpa-big-creek', config['watches'])
        self.assertIn('mpa-point-sur', config['watches'])
        self.assertNotIn('access-vandenberg-maritime', config['watches'])


if __name__ == '__main__':
    unittest.main()

"""The South Big Sur preview exposes local evidence without inventing fishing marks."""
import json
from pathlib import Path
import unittest

from scripts.prepare_regional_mpas import validate_response
from skippercast.pipeline.settings import settings


ROOT = Path(__file__).resolve().parents[1]
RID = 'south-big-sur-san-simeon'


class SouthBigSurRegionTests(unittest.TestCase):
    def test_mpas_and_unqualified_fishing_export(self):
        region = json.loads((ROOT / 'regions' / RID / 'region.json').read_text())
        protected = json.loads((ROOT / 'dist' / region['assets']['protected_areas']).read_text())
        validate_response(protected, region['mpa']['bounds'], 2)
        self.assertEqual({f['properties']['NAME'] for f in protected['features']},
                         {'Piedras Blancas SMR', 'Piedras Blancas SMCA'})
        atlas = json.loads((ROOT / 'dist' / region['assets']['atlas']).read_text())
        self.assertEqual(region['status'], 'preview')
        self.assertEqual([atlas[key] for key in ('targets', 'areas', 'drifts')],
                         [[], [], []])
        self.assertEqual(region['coverage']['bathymetry']['status'], 'research')

    def test_zone_boundary_and_legal_scope(self):
        region = json.loads((ROOT / 'regions' / RID / 'region.json').read_text())
        self.assertEqual(region['contexts']['piedras-south']['marine_zones'],
                         {'coastal': 'PZZ645', 'offshore': 'PZZ670'})
        self.assertEqual(region['contexts']['big-sur-south']['marine_zones'],
                         {'coastal': 'PZZ565', 'offshore': 'PZZ576'})
        config = settings(RID)
        decision = json.loads((ROOT / config['regulations']['review_record']).read_text())
        self.assertIn({'id': RID, 'fishing_bounds': region['fishing_bounds']},
                      decision['reviewed_regions'])
        self.assertIn('mpa-piedras', config['watches'])
        self.assertNotIn('access-vandenberg-maritime', config['watches'])


if __name__ == '__main__':
    unittest.main()

"""Keep the Trinidad–Klamath draft from publishing an unreviewed legal claim.

The package fills the 40.95–41.55° N gap between humboldt-bay-cape-mendocino and
crescent-city (coast campaign segment N6b). It stays a draft until the Northern
regulation review lists its fishing footprint: a preview needs that hash-bound
review (pipeline.regulations.validate_region_binding), and drafts are never
compiled into dist/regions.
"""
import json
import unittest

from skippercast.platform.contracts import load_region
from tests._support import ROOT

ID = 'trinidad-klamath'


class TrinidadKlamathDraftTest(unittest.TestCase):
    def setUp(self):
        self.region = load_region(ID, ROOT)
        self.rules = json.loads((ROOT / 'dist/data/regulations-northern.json').read_text())

    def test_bounds_fill_the_gap_between_neighbouring_packages(self):
        self.assertEqual(self.region['bounds'], [-124.6, 40.95, -124.0, 41.55])
        south = load_region('humboldt-bay-cape-mendocino', ROOT)['bounds']
        north = load_region('crescent-city', ROOT)['bounds']
        self.assertEqual(self.region['bounds'][1], south[3])
        self.assertEqual(self.region['bounds'][3], north[1])
        west, s, east, n = self.region['bounds']
        fw, fs, fe, fn = self.region['fishing_bounds']
        self.assertTrue(west <= fw < fe <= east and s <= fs < fn <= n)
        self.assertEqual(self.region['map']['discovery_bounds'], self.region['bounds'])
        self.assertEqual(self.region['mpa']['bounds'], self.region['bounds'])

    def test_northern_jurisdiction_and_notices(self):
        self.assertEqual(self.region['jurisdiction_id'], 'california-northern')
        self.assertEqual(self.region['assets']['regulations'], 'data/regulations-northern.json')
        notices = {n['id'] for n in self.rules['area_notices']}
        self.assertLessEqual(set(self.region['map']['region_notice_ids']), notices)
        # Reading Rock SMR and SMCA lie inside the footprint.
        self.assertEqual(self.region['mpa']['minimum_features'], 2)

    def test_stays_draft_until_the_footprint_is_legally_reviewed(self):
        reviewed = {r['id'] for r in self.rules['reviewed_regions']}
        if ID not in reviewed:
            self.assertEqual(self.region['status'], 'draft')
            self.assertEqual(self.region['coverage']['regulations']['status'], 'research')
        if self.region['status'] == 'draft':
            self.assertFalse((ROOT / 'dist/regions' / ID).exists())
            index = json.loads((ROOT / 'dist/regions/index.json').read_text())
            self.assertNotIn(ID, {r['id'] for r in index['regions']})

    def test_no_fishing_assets_or_charter_layers(self):
        assets = self.region['assets']
        for key in ('charters', 'ais_evidence', 'commercial_ais', 'daily_evidence'):
            self.assertIsNone(assets[key])
        self.assertNotIn('survey_habitat', assets)
        self.assertNotIn('ready', {c['status'] for c in self.region['coverage'].values()})

    def test_local_references_are_labelled(self):
        stations = self.region['stations']
        self.assertEqual(stations['tide'], '9419059')
        self.assertIn('subordinate', stations['tide_note'])
        self.assertEqual(set(self.region['contexts']), {'trinidad', 'klamath'})
        contexts = {p['context'] for p in self.region['forecast_points']}
        self.assertEqual(contexts, {'trinidad', 'klamath'})
        self.assertEqual(set(self.region['marine_zones'].values()), {'PZZ450', 'PZZ470'})


if __name__ == '__main__':
    unittest.main()

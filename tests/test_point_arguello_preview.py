"""Publication gates for the Point Sal–Point Conception preview."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


class PointArguelloPreview(unittest.TestCase):
    def test_context_is_local_reef_evidence_only(self):
        prefix = 'dist/regions/point-arguello-conception/'
        region = load('regions/point-arguello-conception/region.json')
        context = load(prefix + 'survey-habitat.geojson')
        search = load(prefix + 'search-plans.json')
        atlas = load(prefix + 'atlas.json')
        self.assertEqual(region['status'], 'preview')
        self.assertEqual(context['all_source_outline_count'], 21)
        self.assertEqual(len(context['features']), 4)
        self.assertEqual(len(search['features']), 4)
        self.assertEqual(atlas['targets'], [])
        self.assertEqual(atlas['drifts'], [])
        for feature in context['features']:
            p = feature['properties']
            self.assertEqual(p['species_ids'], ['reef'])
            self.assertEqual(p['habitat_kind'], 'rock')
            self.assertGreaterEqual(p['approx_display_area_m2'], 2500)
            self.assertIs(p['fishing_target'], False)
            self.assertIs(p['fishing_export'], False)
            self.assertIs(p['depth_qualified'], False)
        for feature in search['features']:
            self.assertEqual(feature['properties']['species'], ['reef'])
            self.assertIs(feature['properties']['exportable'], False)

    def test_local_closures_and_unverified_access_are_explicit(self):
        region = load('regions/point-arguello-conception/region.json')
        closures = load('dist/regions/point-arguello-conception/protected-areas.geojson')
        rules = load('dist/data/regulations.json')
        self.assertEqual({f['properties']['NAME'] for f in closures['features']},
                         {'Vandenberg SMR', 'Point Conception SMR'})
        self.assertIn('PZZ673', region['marine_zones'].values())
        self.assertEqual(region['map']['region_notice_ids'], ['vandenberg-conception'])
        self.assertIn('access-vandenberg-maritime', rules['review_required'])
        self.assertIsNone(rules['sources']['access-vandenberg-maritime']['approved_content_sha256'])


if __name__ == '__main__':
    unittest.main()

"""The San Francisco original-cell browse layer must stay research-only."""
import json
from pathlib import Path
import unittest

from shapely.geometry import shape
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]


class NativeHardContextTests(unittest.TestCase):
    def test_published_layer_is_valid_context_outside_federal_exclusions(self):
        layer = json.loads((ROOT / 'dist/data/sf-native-hard-context.geojson').read_text())
        federal = json.loads((ROOT / 'dist/data/noaa-federal-areas.json').read_text())
        self.assertEqual(layer['scope'], 'sf-native-noaa-usgs-hard-bottom-context')
        self.assertEqual(layer['coast_id'], 'san-francisco')
        self.assertGreater(len(layer['features']), 50)
        gea = unary_union([shape(f['geometry']) for f in federal['features']
                           if f['properties']['area_type'] == 'GEA'])
        for feature in layer['features']:
            with self.subTest(feature=feature['properties']['id']):
                props = feature['properties']
                self.assertTrue(shape(feature['geometry']).is_valid)
                self.assertFalse(shape(feature['geometry']).intersects(gea))
                self.assertIs(props['fishing_target'], False)
                self.assertIs(props['exportable'], False)
                self.assertIs(props['legal_clearance'], False)
                self.assertIs(props['fish_confirmed'], False)
                self.assertIs(props['depth_qualified_for_target'], False)
                self.assertLessEqual(props['depth_ft_range'][1], 200)


if __name__ == '__main__':
    unittest.main()

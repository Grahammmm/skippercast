import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class CapeMendocinoContextTests(TestCase):
    def test_source_boundaries_remain_non_fishing_context(self):
        source = json.loads((ROOT / 'catalog/usgs-seafloor-sources.json').read_text())['sources'][0]
        layer = json.loads((ROOT / 'dist/data/cape-mendocino-seafloor-context.geojson').read_text())
        self.assertEqual(layer['source_file_sha256'], source['character_sha256'])
        self.assertEqual(layer['sector_id'], 'humboldt-cape')
        self.assertEqual(len(layer['features']), 43)
        self.assertTrue(all(f['properties']['fishing_target'] is False and
                            f['properties']['exportable'] is False and
                            f['properties']['depth_qualified'] is False and
                            f['properties']['fish_confirmed'] is False
                            for f in layer['features']))
        self.assertTrue(all(f['geometry']['type'] in {'Polygon', 'MultiPolygon'} for f in layer['features']))
        self.assertIn('no legal 200-foot depth qualification', layer['limitations'].lower())

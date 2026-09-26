"""Compiled home ports point to existing regional marine forecast locations."""
import json
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]


class HomePortDirectory(TestCase):
    def test_compiled_ports_match_reviewed_regions_and_forecast_points(self):
        source = json.loads((ROOT / 'catalog/home-ports.json').read_text())
        compiled = json.loads((ROOT / 'dist/data/home-ports.json').read_text())
        self.assertEqual(len(compiled['ports']), len(source['ports']))
        self.assertEqual(len({p['id'] for p in compiled['ports']}), len(compiled['ports']))
        for raw, port in zip(source['ports'], compiled['ports'], strict=True):
            region = json.loads((ROOT / 'dist/regions' / raw['region'] / 'region.json').read_text())
            point = next(p for p in region['forecast_points'] if p['id'] == raw['forecast_point'])
            self.assertEqual(port['view'][:2], [point['latitude'], point['longitude']])
            self.assertEqual(port['match'], raw['match'])
            self.assertEqual(port['region'], raw['region'])

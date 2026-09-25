import json
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from unittest import TestCase

from skippercast.platform.sectors import compile_sectors

ROOT = Path(__file__).resolve().parents[1]


class CoastalSectorTests(TestCase):
    def test_every_coast_is_partitioned_without_promoting_unmapped_water(self):
        packet = compile_sectors()
        coasts = {item['id']: item for item in json.loads((ROOT / 'catalog/coasts.json').read_text())['regions']}
        self.assertEqual(len(packet['sectors']), 19)
        for coast_id, coast in coasts.items():
            sectors = [s for s in packet['sectors'] if s['coast'] == coast_id]
            self.assertEqual(sectors[0]['latitude'][0], coast['latitude'][0])
            self.assertEqual(sectors[-1]['latitude'][1], coast['latitude'][1])
            self.assertTrue(all(s['status'] == 'discovery' for s in sectors))
            self.assertTrue(all('not been established' in s['note'] for s in sectors))
        expected = 0
        for region in ('morro-bay', 'cambria-san-simeon', 'southern-california'):
            config = json.loads((ROOT / 'regions' / region / 'region.json').read_text())
            atlas = json.loads((ROOT / 'dist' / config['assets']['atlas']).read_text())
            expected += len(atlas['targets'])
        self.assertEqual(sum(s['published_candidate_points'] for s in packet['sectors']), expected)

    def test_gap_in_sectors_fails_before_publication(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'catalog').mkdir()
            (root / 'dist/regions').mkdir(parents=True)
            shutil.copy(ROOT / 'catalog/coasts.json', root / 'catalog/coasts.json')
            shutil.copy(ROOT / 'dist/regions/index.json', root / 'dist/regions/index.json')
            for entry in json.loads((ROOT / 'dist/regions/index.json').read_text())['regions']:
                config = ROOT / 'regions' / entry['id'] / 'region.json'
                target = root / 'regions' / entry['id'] / 'region.json'
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(config, target)
                atlas = json.loads(config.read_text())['assets']['atlas']
                output = root / 'dist' / atlas
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / 'dist' / atlas, output)
            source = json.loads((ROOT / 'catalog/coastal-sectors.json').read_text())
            source['sectors'][0]['latitude'][0] = 41.71
            (root / 'catalog/coastal-sectors.json').write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, 'gaps or overlaps'):
                compile_sectors(root)

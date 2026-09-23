import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PrimaryStrategyTests(unittest.TestCase):
    def test_every_published_target_has_a_reviewed_starter_method(self):
        catalog = json.loads((ROOT / 'catalog/primary-strategies.json').read_text())
        for region_file in (ROOT / 'regions').glob('*/region.json'):
            region = json.loads(region_file.read_text())
            if region['status'] == 'draft':
                continue
            packet = json.loads((ROOT / 'dist/regions' / region['id'] / 'strategies.json').read_text())
            self.assertEqual(set(packet['strategies']), set(region['species']))
            self.assertEqual(packet['reviewed_at'], catalog['reviewed_at'])
            for species_id in region['species']:
                strategy = packet['strategies'][species_id]
                self.assertEqual(strategy, catalog['species'][species_id])
                self.assertGreaterEqual(len(strategy['find']), 2)
                self.assertGreaterEqual(len(strategy['steps']), 3)
                self.assertTrue(strategy['rig'])

    def test_rebuild_is_repeatable(self):
        files = sorted((ROOT / 'dist/regions').glob('*/strategies.json'))
        before = {file: file.read_bytes() for file in files}
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_primary_strategies.py')], cwd=ROOT, check=True, capture_output=True)
        self.assertEqual(before, {file: file.read_bytes() for file in files})


if __name__ == '__main__':
    unittest.main()

"""Keep the statewide promotion queue complete and honest."""
import json
import unittest
from pathlib import Path

from skippercast.platform.readiness import compile_readiness


ROOT = Path(__file__).resolve().parents[1]


class AtlasReadinessTests(unittest.TestCase):
    def test_every_discovery_sector_has_a_non_promotion_queue_entry(self):
        compile_readiness(ROOT)
        report = json.loads((ROOT / 'dist/data/california-atlas-readiness.json').read_text())
        source = json.loads((ROOT / 'catalog/coastal-sectors.json').read_text())
        self.assertEqual({row['sector_id'] for row in report['sectors']},
                         {row['id'] for row in source['sectors']})
        self.assertEqual(len(report['sectors']), 19)
        for row in report['sectors']:
            self.assertIn(row['status'], {'source-review-only', 'partial-local-targets'})
            self.assertEqual(bool(row['published_candidate_points_in_band']),
                             row['status'] == 'partial-local-targets')
            self.assertGreaterEqual(len(row['remaining_promotion_gates']), 6)
            self.assertNotIn('latitude', row)
            self.assertNotIn('longitude', row)

    def test_missing_source_sector_fails_closed(self):
        from tempfile import TemporaryDirectory
        import shutil
        with TemporaryDirectory() as work:
            root = Path(work)
            for relative in ('dist/data/coastal-sectors.json',
                             'dist/data/noaa-native-sector-review.json',
                             'dist/data/noaa-survey-discovery.json',
                             'dist/regions/index.json'):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            path = root / 'dist/data/noaa-native-sector-review.json'
            packet = json.loads(path.read_text())
            packet['sectors'].pop()
            path.write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError, 'missing or has duplicate'):
                compile_readiness(root)

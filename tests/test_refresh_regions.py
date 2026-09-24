"""Draft source checks must be isolated from published regional feeds."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.refresh_regions import refresh


class DraftRehearsalTests(unittest.TestCase):
    def test_one_draft_produces_only_its_local_receipt(self):
        with tempfile.TemporaryDirectory(dir=Path('var')) as directory:
            output = Path(directory)
            data = {'generated_at': '2026-09-24T00:00:00Z', 'completed_at': '2026-09-24T00:00:01Z',
                    'health': {'status': 'degraded', 'issues': ['fixture']},
                    'regulations': {}, 'sources': {}}
            with patch('scripts.refresh_regions.daily', return_value=data) as collector, \
                    patch('scripts.refresh_regions.coverage', return_value={'status': 'fixture', 'species': {}}):
                rows = refresh('daily', output, only_region='bodega-point-reyes', include_drafts=True)
            self.assertEqual([row['region_id'] for row in rows], ['bodega-point-reyes'])
            self.assertEqual(collector.call_count, 1)
            self.assertTrue((output / 'regions/bodega-point-reyes/regulations-health.json').is_file())
            self.assertFalse((output / 'latest.json').exists())
            self.assertFalse((output / 'regions/morro-bay').exists())

    def test_draft_cannot_enter_regular_or_external_output(self):
        with tempfile.TemporaryDirectory(dir=Path('var')) as directory:
            with self.assertRaisesRegex(ValueError, 'was not collected'):
                refresh('daily', Path(directory), only_region='bodega-point-reyes')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'unpublished var'):
                refresh('daily', Path(directory), only_region='bodega-point-reyes', include_drafts=True)


if __name__ == '__main__':
    unittest.main()

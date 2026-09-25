"""Draft source checks must be isolated from published regional feeds."""
import tempfile
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.refresh_regions import refresh
from skippercast.platform.contracts import REPO, load_region


class DraftRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (REPO / 'var').mkdir(exist_ok=True)

    def test_one_draft_produces_only_its_local_receipt(self):
        draft = deepcopy(load_region('crescent-city'))
        draft['status'] = 'draft'
        with tempfile.TemporaryDirectory(dir=REPO / 'var') as directory:
            output = Path(directory)
            data = {'generated_at': '2026-09-24T00:00:00Z', 'completed_at': '2026-09-24T00:00:01Z',
                    'health': {'status': 'degraded', 'issues': ['fixture']},
                    'regulations': {}, 'sources': {}}
            with patch('scripts.refresh_regions.load_region', return_value=draft), \
                    patch('scripts.refresh_regions.daily', return_value=data) as collector, \
                    patch('scripts.refresh_regions.coverage', return_value={'status': 'fixture', 'species': {}}):
                rows = refresh('daily', output, only_region='crescent-city', include_drafts=True)
            self.assertEqual([row['region_id'] for row in rows], ['crescent-city'])
            self.assertEqual(collector.call_count, 1)
            self.assertTrue((output / 'regions/crescent-city/regulations-health.json').is_file())
            self.assertFalse((output / 'latest.json').exists())
            self.assertFalse((output / 'regions/morro-bay').exists())

    def test_draft_cannot_enter_regular_or_external_output(self):
        draft = deepcopy(load_region('crescent-city'))
        draft['status'] = 'draft'
        with tempfile.TemporaryDirectory(dir=REPO / 'var') as directory:
            with patch('scripts.refresh_regions.load_region', return_value=draft), \
                    self.assertRaisesRegex(ValueError, 'was not collected'):
                refresh('daily', Path(directory), only_region='crescent-city')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'unpublished var'):
                refresh('daily', Path(directory), only_region='crescent-city', include_drafts=True)


if __name__ == '__main__':
    unittest.main()

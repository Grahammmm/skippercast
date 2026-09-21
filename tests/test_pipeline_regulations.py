from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import unittest
from skippercast.pipeline.regulations import REGISTRY, regulatory_snapshot


class RegulationChecks(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(REGISTRY.read_text())
        self.now = datetime(2026, 9, 21, 18, tzinfo=timezone.utc)
        self.sources = {}
        for ident, definition in self.registry['sources'].items():
            definition['approved_content_sha256'] = 'a' * 64
            self.sources[ident] = {'status': 'ok', 'checked_at': self.now.isoformat(),
                                   'data_retrieved_at': self.now.isoformat(),
                                   'data': {'content_sha256': 'a' * 64}}

    def test_changes_stay_flagged_until_review_not_next_fetch(self):
        key = 'rules-salmon'
        self.sources[key]['data']['content_sha256'] = 'b' * 64
        for day in range(3):
            now = self.now + timedelta(days=day)
            self.sources[key]['data_retrieved_at'] = now.isoformat()
            result = regulatory_snapshot(self.sources, now, self.registry)
            self.assertEqual(result['checks'][key]['status'], 'changed')
            self.assertIn(key, result['review_required'])
        self.assertEqual(self.registry['sources'][key]['approved_content_sha256'], 'a' * 64)

    def test_failed_retained_stale_future_and_missing_are_not_verified(self):
        for status in ['failed', 'retained', 'stale', 'missing']:
            self.sources['rules-central']['status'] = status
            result = regulatory_snapshot(self.sources, self.now, self.registry)
            self.assertEqual(result['checks']['rules-central']['status'], 'unavailable')
        self.sources['rules-central']['status'] = 'ok'
        for hours in [-37, 2]:
            self.sources['rules-central']['data_retrieved_at'] = (self.now + timedelta(hours=hours)).isoformat()
            self.assertEqual(regulatory_snapshot(self.sources, self.now, self.registry)['checks']['rules-central']['status'], 'unavailable')
        del self.sources['rules-central']
        self.assertEqual(regulatory_snapshot(self.sources, self.now, self.registry)['checks']['rules-central']['status'], 'unavailable')

    def test_new_source_needs_review_even_if_http_succeeded(self):
        self.registry['sources']['rules-book']['approved_content_sha256'] = None
        result = regulatory_snapshot(self.sources, self.now, self.registry)
        self.assertEqual(result['checks']['rules-book']['status'], 'unreviewed')

    def test_reviewed_matching_sources_pass_and_registry_is_not_mutated(self):
        original = deepcopy(self.registry)
        result = regulatory_snapshot(self.sources, self.now, self.registry)
        self.assertEqual(result['review_required'], [])
        self.assertEqual(self.registry, original)
        for profile in result['species'].values():
            self.assertTrue(set(profile['source_ids']).issubset(result['sources']))

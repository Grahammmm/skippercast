"""Every published latest.json carries published_at and run_id (P0-04)."""
from datetime import datetime, timezone
import os
from unittest import TestCase
from unittest.mock import patch

from skippercast.pipeline import coastal_watch
from skippercast.pipeline.collect import publication, run_id, validate
from skippercast.pipeline.live import collect as live


class RunIdTests(TestCase):
    def test_github_run_id_else_local(self):
        self.assertEqual(run_id({'GITHUB_RUN_ID': '18123456789'}), '18123456789')
        self.assertEqual(run_id({'GITHUB_RUN_ID': '  '}), 'local')
        self.assertEqual(run_id({}), 'local')

    def test_publication_fields(self):
        fields = publication({'GITHUB_RUN_ID': '7'})
        self.assertEqual(set(fields), {'published_at', 'run_id'})
        self.assertEqual(fields['run_id'], '7')
        self.assertRegex(fields['published_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')


class FeedModelTests(TestCase):
    def test_live_feed_carries_run_id(self):
        def fake_source(ident, name, kind, url, max_age, loader, collected, previous):
            return {'id': ident, 'status': 'ok', 'url': url, 'data': {'sample_at': '2026-09-21T18:26:00Z'}}
        with patch('skippercast.pipeline.live.source', side_effect=fake_source), \
                patch.dict(os.environ, {'GITHUB_RUN_ID': '99'}):
            data = live(datetime(2026, 9, 21, 19, tzinfo=timezone.utc))
        self.assertEqual(data['run_id'], '99')
        self.assertIn('published_at', data)

    def test_coastal_feed_carries_run_id(self):
        with patch.object(coastal_watch, 'source', side_effect=lambda ident, *a, **k: (
                {'id': ident, 'status': 'failed', 'data': None})), \
                patch.dict(os.environ, {'GITHUB_RUN_ID': '5'}):
            data = coastal_watch.collect(now=datetime(2026, 9, 21, 19, tzinfo=timezone.utc))
        self.assertEqual(data['run_id'], '5')
        self.assertIn('published_at', data)

    def test_daily_validation_accepts_legacy_feeds_and_requires_both_fields(self):
        base = {'schema_version': 1, 'generated_at': '2026-09-21T19:00:00Z', 'sources': {}, 'reports': []}
        validate(base)  # previous generations published before run_id existed stay readable
        validate({**base, 'published_at': '2026-09-21T19:05:00Z', 'run_id': 'local'})
        for broken in ({'run_id': '1'}, {'published_at': '2026-09-21T19:05:00Z'},
                       {'published_at': '2026-09-21T19:05:00Z', 'run_id': ''},
                       {'published_at': '2026-09-21T19:05:00', 'run_id': '1'}):
            with self.assertRaises(ValueError, msg=broken):
                validate({**base, **broken})

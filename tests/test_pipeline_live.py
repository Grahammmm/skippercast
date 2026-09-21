from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from skippercast.pipeline.live import collect


class LiveObservationsTests(TestCase):
    def test_all_sources_keep_station_identity_and_original_times(self):
        now = datetime(2026, 9, 21, 19, tzinfo=timezone.utc)
        def fake_source(ident, name, kind, url, max_age, loader, collected, previous):
            return {'id': ident, 'status': 'ok', 'url': url,
                    'data': {'sample_at': '2026-09-21T18:26:00Z'}}
        with patch('skippercast.pipeline.live.source', side_effect=fake_source):
            data = collect(now)
        self.assertEqual(data['generated_at'], '2026-09-21T19:00:00Z')
        self.assertEqual(data['health']['status'], 'ok')
        self.assertEqual(data['sources']['diablo']['data']['sample_at'], '2026-09-21T18:26:00Z')
        self.assertIn('46215', data['sources']['diablo']['station_url'])
        self.assertIn('46028', data['sources']['offshore']['station_url'])

    def test_retained_source_is_degraded_not_relabelled_current(self):
        previous = {'sources': {'diablo': {'status': 'ok', 'data': {'sample_at': 'old'}}}}
        def fake_source(ident, name, kind, url, max_age, loader, collected, old):
            if ident == 'diablo':
                self.assertEqual(old, previous['sources']['diablo'])
                return {**old, 'status': 'retained'}
            return {'status': 'failed', 'data': None}
        with patch('skippercast.pipeline.live.source', side_effect=fake_source):
            data = collect(previous=previous)
        self.assertEqual(data['health']['status'], 'degraded')
        self.assertEqual(len(data['health']['issues']), 3)
        self.assertEqual(data['sources']['diablo']['data']['sample_at'], 'old')

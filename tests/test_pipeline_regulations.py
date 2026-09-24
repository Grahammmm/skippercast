from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import unittest
from skippercast.pipeline.regulations import REGISTRY, regulatory_snapshot, content_hash


class RegulationChecks(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(REGISTRY.read_text())
        self.now = datetime(2026, 9, 21, 18, tzinfo=timezone.utc)
        self.sources = {}
        for ident, definition in self.registry['sources'].items():
            definition['approved_content_sha256'] = 'a' * 64
            self.sources[ident] = {'status': 'ok', 'url': definition['url'], 'checked_at': self.now.isoformat(),
                                   'data_retrieved_at': self.now.isoformat(),
                                   'data': {'content_sha256': 'a' * 64, 'normalization': definition['normalization']}}
        self.registry['approved_rules_content_sha256'] = content_hash(self.registry)

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

    def test_spatial_season_requires_bounded_latitudes_and_a_dependency(self):
        window=self.registry['species']['salmon']['windows'][0]
        window['geography']={'kind':'latitude-band','south':35.0,'north':35.4,
                             'source_id':'rules-salmon','note':'Reviewed latitude-restricted opening.'}
        regulatory_snapshot(self.sources,self.now,self.registry)
        for broken in ({'north':91},{'south':35.4},{'source_id':'unknown-source'}):
            changed=deepcopy(self.registry)
            changed['species']['salmon']['windows'][0]['geography'].update(broken)
            with self.assertRaises(ValueError):
                regulatory_snapshot(self.sources,self.now,changed)

    def test_new_region_accepts_more_species_without_silently_dropping_them(self):
        from skippercast.platform.contracts import REPO
        registry=json.loads((REPO/'dist/regions/southern-california/regulations.json').read_text())
        self.assertGreater(len(registry['species']),7)
        result=regulatory_snapshot({},self.now,registry)
        self.assertIn('lobster',result['species'])
        self.assertEqual(result['checks']['rules-southern']['status'],'unavailable')
        registry['species']['lobster']['source_ids']=['unknown-source']
        with self.assertRaises(ValueError):regulatory_snapshot({},self.now,registry)

    def test_timed_opening_requires_an_offset_and_matching_start_date(self):
        profile = self.registry['species']['lingcod']
        profile['windows'] = [{'start': '2026-10-02', 'end': '2026-12-31', 'start_at': '2026-10-02T18:00:00-07:00'}]
        regulatory_snapshot(self.sources, self.now, self.registry)
        for value in ('2026-10-02T18:00:00', '2026-10-03T18:00:00-07:00', 'invalid'):
            profile['windows'][0]['start_at'] = value
            with self.assertRaises(ValueError):regulatory_snapshot(self.sources,self.now,self.registry)

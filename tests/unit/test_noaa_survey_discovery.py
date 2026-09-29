from datetime import datetime, timezone
import json
from unittest import TestCase

from scripts.discover_noaa_surveys import scan


class NoaaSurveyDiscoveryTests(TestCase):
    def setUp(self):
        self.sectors = [{'id': 'test-coast', 'bounds': [-125, 40, -124, 41]}]
        self.now = datetime(2026, 9, 23, tzinfo=timezone.utc)

    def test_catalog_leads_keep_original_receipt_and_do_not_claim_bottom_coverage(self):
        raw = json.dumps({'features': [{'attributes': {'SURVEY_ID': 'H11978', 'LOCALITY': 'Northern California',
            'SURVEY_YEAR': 2008, 'BAGS_EXIST': 'Y', 'DOWNLOAD_URL': 'https://www.ngdc.noaa.gov/nos/H10001-H12000/H11978.html'}}]}).encode()
        result = scan(self.sectors, now=self.now, fetcher=lambda url: raw)
        self.assertEqual(result['health']['status'], 'ok')
        self.assertEqual(result['distinct_survey_leads'], 1)
        self.assertIn('not a verified BAG grid', result['method'])
        self.assertEqual(result['sectors'][0]['surveys'][0]['id'], 'H11978')
        self.assertEqual(len(result['sectors'][0]['raw_sha256']), 64)

    def test_incomplete_page_does_not_replace_prior_survey_with_empty_success(self):
        previous = scan(self.sectors, now=self.now, fetcher=lambda url: b'{"features":[]}')
        previous['sectors'][0]['surveys'] = [{'id': 'H11978', 'year': 2008}]
        result = scan(self.sectors, previous, now=self.now,
                      fetcher=lambda url: b'{"features":[],"exceededTransferLimit":true}')
        self.assertEqual(result['health']['status'], 'degraded')
        self.assertEqual(result['sectors'][0]['status'], 'retained')
        self.assertEqual(result['sectors'][0]['retrieved_at'], previous['sectors'][0]['retrieved_at'])
        self.assertEqual(result['sectors'][0]['surveys'][0]['id'], 'H11978')

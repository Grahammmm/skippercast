from datetime import datetime, timezone
from unittest import TestCase

from scripts.audit_noaa_survey_products import inspect, audit


class NoaaSurveyProductsTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 23, tzinfo=timezone.utc)
        self.lead = {'id': 'H11983', 'catalog_url': 'https://www.ngdc.noaa.gov/nos/H10001-H12000/H11983.html'}
        self.discovery = {'sectors': [{'surveys': [self.lead, self.lead]}]}

    def test_only_original_noaa_products_for_matching_survey_are_retained(self):
        page = b'''<html><a href="//data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11983/BAG/grid.bag">BAG</a>
          <a href="//data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11983/DR/report.pdf">DR</a>
          <a href="https://evil.example/H11983/BAG/fake.bag">bad</a>
          <a href="https://data.ngdc.noaa.gov/H00000/BAG/other.bag">other</a></html>'''
        row = inspect(self.lead, now=self.now, fetcher=lambda url: page)
        self.assertEqual(len(row['products']['bag']), 1)
        self.assertEqual(len(row['products']['report']), 1)
        self.assertEqual(len(row['catalog_sha256']), 64)
        self.assertNotIn('qualified', row)

    def test_failed_page_retains_dated_products_and_marks_degraded(self):
        prior = audit(self.discovery, now=self.now,
                      inspector=lambda lead, now: inspect(lead, now=now, fetcher=lambda url: b'<a href="/H11983/BAG/a.bag">BAG</a>'))
        result = audit(self.discovery, previous=prior, now=self.now,
                       inspector=lambda lead, now: (_ for _ in ()).throw(OSError('HTTP 503')))
        self.assertEqual(result['survey_count'], 1)
        self.assertEqual(result['health']['status'], 'degraded')
        self.assertEqual(result['surveys'][0]['status'], 'retained')
        self.assertEqual(result['surveys'][0]['retrieved_at'], prior['surveys'][0]['retrieved_at'])
        self.assertEqual(result['last_complete_scan_at'], prior['last_complete_scan_at'])

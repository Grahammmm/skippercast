import email.message
import importlib.util
from urllib.error import HTTPError
from datetime import datetime, timezone
import unittest
from research.lib.paths import ROOT


SPEC = importlib.util.spec_from_file_location('bag_triage', ROOT / 'research/scripts' / 'triage_noaa_bag_files.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class BagTriageTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/D00001-D02000/D00182/BAG/D00182_MB_1m_MLLW_1of1.bag'
        self.discovery = {'scope':'noaa-bag-survey-discovery','sector_count':1,'sectors':[{'sector_id':'sector','surveys':[{'id':'D00182'}]}]}
        self.products = {'scope':'noaa-survey-product-links','survey_count':1,'surveys':[{'id':'D00182','products':{'bag':[self.url],'report':['report']}}]}

    def test_metadata_only_queue(self):
        result = mod.inventory(self.discovery, self.products, now=datetime(2026,9,23,tzinfo=timezone.utc), fetcher=lambda url:(500000,'Tue, 01 Jan 2019 00:00:00 GMT'))
        self.assertEqual(result['health']['status'],'ok')
        self.assertEqual(result['native_review_hint_count'],1)
        self.assertIn('triage only',result['method'])

    def test_rejects_unrelated_survey_url(self):
        self.products['surveys'][0]['products']['bag'] = [self.url.replace('/D00182/BAG/','/D00183/BAG/')]
        with self.assertRaises(ValueError):
            mod.inventory(self.discovery,self.products,fetcher=lambda url:(500000,None))


class _Response:
    def __init__(self, url):
        self.status, self.url, self.headers = 200, url, {'Content-Length':'500000','Last-Modified':'Tue, 01 Jan 2019 00:00:00 GMT'}
    def __enter__(self): return self
    def __exit__(self, *exc): return False


class BagHeadRateLimitTests(unittest.TestCase):
    URL = 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/D00001-D02000/D00182/BAG/D00182_MB_1m_MLLW_1of1.bag'

    def opener(self, failures, retry_after=None):
        calls = []
        def open_(request, timeout):
            calls.append(request.get_method())
            if len(calls) <= failures:
                headers = email.message.Message()
                if retry_after is not None:
                    headers['Retry-After'] = retry_after
                raise HTTPError(self.URL, 429, 'Too Many Requests', headers, None)
            return _Response(self.URL)
        return open_, calls

    def test_retries_429_honouring_retry_after(self):
        opener, calls = self.opener(2, retry_after='7')
        waits = []
        self.assertEqual(mod.head(self.URL, opener=opener, sleep=waits.append), (500000, 'Tue, 01 Jan 2019 00:00:00 GMT'))
        self.assertEqual(calls, ['HEAD', 'HEAD', 'HEAD'])
        self.assertEqual(waits, [7.0, 7.0])

    def test_backs_off_without_retry_after_and_caps_the_wait(self):
        opener, _ = self.opener(4, retry_after='3600')
        waits = []
        mod.head(self.URL, opener=opener, sleep=waits.append)
        self.assertEqual(waits, [mod.RATE_LIMIT_MAX_WAIT] * 4)
        opener, _ = self.opener(2)
        waits = []
        mod.head(self.URL, opener=opener, sleep=waits.append)
        self.assertEqual(waits, [2.0, 4.0])

    def test_gives_up_after_the_last_attempt(self):
        opener, calls = self.opener(mod.RATE_LIMIT_ATTEMPTS)
        with self.assertRaises(HTTPError):
            mod.head(self.URL, opener=opener, sleep=lambda s: None)
        self.assertEqual(len(calls), mod.RATE_LIMIT_ATTEMPTS)

    def test_other_http_errors_are_not_retried(self):
        calls = []
        def opener(request, timeout):
            calls.append(1)
            raise HTTPError(self.URL, 404, 'Not Found', email.message.Message(), None)
        with self.assertRaises(HTTPError):
            mod.head(self.URL, opener=opener, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()

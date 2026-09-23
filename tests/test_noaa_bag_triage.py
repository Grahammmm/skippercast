import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location('bag_triage', Path(__file__).resolve().parents[1] / 'scripts' / 'triage_noaa_bag_files.py')
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


if __name__ == '__main__':
    unittest.main()

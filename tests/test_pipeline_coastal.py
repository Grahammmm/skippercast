import unittest
from datetime import datetime, timezone
from skippercast.pipeline.coastal_watch import parse_enso, parse_rules, located_reports, groundfish_table_loader
from skippercast.pipeline.collect import source
from skippercast.platform.coasts import compile_coasts


class CoastalWatchTests(unittest.TestCase):
    def setUp(self):
        self.catalog=compile_coasts();self.coast=next(r for r in self.catalog['regions'] if r['id']=='central')
        self.now=datetime(2026,9,22,15,tzinfo=timezone.utc)

    def test_dates_are_publisher_dates_not_download_clocks(self):
        data=parse_enso('<h1>ENSO Diagnostic Discussion</h1><p>10 September 2026</p><p>ENSO Alert System Status: <a>El Niño Advisory</a></p>')
        self.assertEqual(data['published_date'],'2026-09-10');self.assertNotIn('issued_at',data)
        with self.assertRaises(ValueError):parse_enso('<h1>NOAA gateway error</h1>')
        html='Current California Ocean Recreational Fishing Regulations - Central Region. This summary of current regulations was updated on September 1, 2026.'
        data=parse_rules(html,self.coast);self.assertEqual(data['published_date'],'2026-09-01');self.assertIsNone(data['permission_to_fish'])
        with self.assertRaises(ValueError):parse_rules(html.replace('Central Region','Southern Region'),self.coast)

    def test_failures_retain_original_source_time(self):
        old={'data':{'published_date':'2026-09-10'},'data_retrieved_at':'2026-09-20T15:00:00Z','last_success_at':'2026-09-20T15:00:00Z'}
        def fail(client):raise ValueError('offline')
        got=source('enso','NOAA','page-watch','https://www.cpc.ncep.noaa.gov/',1080,fail,self.now,old)
        self.assertEqual(got['status'],'retained');self.assertEqual(got['data_retrieved_at'],old['data_retrieved_at'])

    def test_each_coast_watches_its_own_official_groundfish_pdf(self):
        urls=[r['groundfish_table_url'] for r in self.catalog['regions']]
        self.assertEqual(len(urls),len(set(urls)))
        self.assertTrue(all(url.startswith('https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=') for url in urls))
        class PDFClient:
            def get(self,url,**options):
                self.options=options
                return b'%PDF-1.7\nexample'
        client=PDFClient()
        result=groundfish_table_loader(client,urls[0])
        self.assertEqual(result['normalization'],'pdf-bytes-v1')
        self.assertIsNone(result['permission_to_fish'])
        self.assertEqual(client.options,{'as_pdf':True,'as_binary':True})
        with self.assertRaises(ValueError):groundfish_table_loader(type('Bad',(),{'get':lambda *a,**kw:b'<html>error</html>'})(),urls[0])
        class SourceClient:
            def __init__(self,now):self.requests=[]
            def get(self,url,**options):return b'%PDF-1.7\nexample'
        prior={'data':{'content_sha256':'0'*64}}
        checked=source('northern-groundfish-table','CDFW northern','pdf-watch',urls[0],36,
                       lambda c:groundfish_table_loader(c,urls[0]),self.now,prior,SourceClient)
        self.assertEqual(checked['status'],'ok')
        self.assertIs(checked['changed_since_previous'],True)

    def test_port_reports_and_enso_alone_cannot_promote_species(self):
        report={'date':'2026-09-21','coordinates':None,'port':'Morro Bay','source_url':'https://example.org/report','catches':[{'species':'yellowfin','count':5}]}
        for records in [[],[report]]:
            got=located_reports(self.coast,records,self.now,self.catalog['policy'])
            self.assertTrue(all(w['status']=='watch-only' for w in got))

    def test_new_reports_need_reviewed_locations_distinct_sources_and_dates(self):
        report={'date':'2026-09-21','coordinates':[-121.4,35.6],'coordinate_role':'fishing-observation','location_review':'reviewed','original_publisher_id':'one','publisher_review':'reviewed','source_url':'https://one.example/report','catches':[{'species':'yellowfin','count':5}]}
        other={**report,'date':'2026-09-20','source_url':'https://two.example/report','original_publisher_id':'two'}
        def result(rows):return next(w for w in located_reports(self.coast,rows,self.now,self.catalog['policy']) if w['target']=='yellowfin')
        self.assertEqual(result([report,other])['status'],'recent-located-reports')
        self.assertFalse(result([report,other])['auto_add_to_qualified_map'])
        for bad in [{**other,'coordinates':[-118,33]},{**other,'date':'2026-10-01'},{**other,'date':'2026-08-01'},{**other,'location_review':'unreviewed'},{**other,'original_publisher_id':'one'}]:
            self.assertEqual(result([report,bad])['status'],'watch-only')

if __name__=='__main__':unittest.main()

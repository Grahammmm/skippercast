import base64
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from skippercast.pipeline.verification import forecast_records,merge_records,verify
from skippercast.pipeline.ocean import dap_arrays,vector,bounds_indices
from tests._support import ROOT


class IntelligenceTests(unittest.TestCase):
    def test_new_regional_points_never_inherit_old_verification_station_rows(self):
        from skippercast.pipeline.intelligence import model_source
        region={'forecast_points':[{'name':'New island','latitude':34,'longitude':-120}],
                'intelligence':{'verification_stations':[{'name':'Buoy','latitude':35,'longitude':-121}]}}
        expected=[{'name':'New island','latitude':34,'longitude':-120},{'name':'Buoy','latitude':35,'longitude':-121}]
        now=datetime.now(timezone.utc)
        with patch('skippercast.pipeline.intelligence.source') as capture:
            old={'data':{'requested_points':expected[1:]}}
            model_source('gfs_global',region,now,old)
            self.assertIsNone(capture.call_args.args[-1])
            model_source('gfs_global',region,now,{'data':None,'status':'failed'})
            self.assertIsNone(capture.call_args.args[-1])
            compatible={'data':{'requested_points':expected}}
            model_source('gfs_global',region,now,compatible)
            self.assertIs(capture.call_args.args[-1],compatible)

    def test_forecasts_are_prospective_immutable_and_not_counted_twice(self):
        station={'id':'46215','variables':['wave_height']}
        data={'meta':{'last_run_initialisation_time':1000,'data_end_time':9000},'points':[{'latitude':35.2,'longitude':-120.85,'hourly_units':{'wave_height':'ft'},'hourly':{'time':[2000,5000,10000],'wave_height':[8,3,4]}}]}
        records=forecast_records('ncep_gfswave016',data,3000,[station]);self.assertEqual(len(records),1)
        altered=[dict(records[0],value=999,acquired_at=6000)]
        self.assertEqual(merge_records(records,altered,6000)[0]['value'],3)
        obs=[{'id':'o','station':'46215','variable':'wave_height','time':5000,'value':2,'unit':'ft'}]
        report=verify(records*2,obs,6000);self.assertEqual(report['matched_samples'],1);self.assertEqual(report['groups'][0]['bias'],1)
        self.assertEqual(verify(altered,obs,6000)['matched_samples'],0)
        self.assertEqual(verify(records,obs,4500)['matched_samples'],0)
        self.assertEqual(report['status'],'collecting history')

    def test_dap_parser_keeps_fill_and_zeros_and_current_direction_is_toward(self):
        raw='Dataset { ignored }\n---------------------------------------------\nu.u[1][1][3]\n[0][0], 0, -32767, 50\n'
        self.assertEqual(dap_arrays(raw)['u.u'],[0,-32767,50]);self.assertEqual(vector(0,0),(0,0))
        self.assertEqual(vector(1,0)[1],90);self.assertEqual(vector(0,-1)[1],180);self.assertIsNone(vector(float('nan'),0))
        with self.assertRaises(ValueError):dap_arrays('<html>Error</html>')
        with self.assertRaises(ValueError):bounds_indices([30,31],35,36)

    @unittest.skipUnless(importlib.util.find_spec('eccodes'),'Optional GRIB decoder not installed')
    def test_real_noaa_probabilities_preserve_thresholds_and_grid_edge_points(self):
        from skippercast.pipeline.wave_ensemble import decode_probabilities
        fixture=json.loads((ROOT/'tests/fixtures/gefs-wave-probability.json').read_text())
        rows=decode_probabilities(base64.b64decode(fixture['base64']),[{'id':'edge','latitude':35.3,'longitude':-121.75},{'id':'far','latitude':0,'longitude':0}])
        self.assertEqual(len(rows),8)
        one=next(r for r in rows if r['threshold_m']==1)
        self.assertEqual(one['threshold_ft'],3.281);self.assertEqual(one['points'][0]['percent'],100)
        self.assertEqual(one['points'][0]['requested'],[35.3,-121.75])
        self.assertIsNone(one['points'][1]['percent'])
        self.assertLess(one['points'][0]['distance_km'],30)


class GefsEnsembleTests(unittest.TestCase):
    """The wind ensemble reads SkipperCast's own NOAA GEFS build, not a third-party API."""
    CYCLE=1790467200

    def setUp(self):
        import os,tempfile
        from unittest.mock import patch as mock_patch
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.region={'id':'test-region','forecast_points':[{'id':'a','latitude':35.5,'longitude':-121.5},{'id':'b','latitude':35.0,'longitude':-121.0}],
                                                   'intelligence':{'wind_ensemble_model':'gfs025'}}
        env=mock_patch.dict(os.environ,{'SKIPPERCAST_FORECAST_ROOT':str(self.root)});env.start();self.addCleanup(env.stop)
        times=[self.CYCLE+h*3600 for h in (0,3,6)]
        def series(member,values):return [list(values) for _ in range(31)]
        wind=series(0,[0,3,6]);wind[1]=[2,None,2]
        gust=series(0,[1,5,8]);gust[2]=[0,0,0]
        self.write('manifest.json',{'model':'ncep_gefs025','sea_radius_km':30,'meta':{'last_run_initialisation_time':self.CYCLE,'last_run_modification_time':self.CYCLE+5*3600,'data_end_time':times[-1]},
                                    'upstream':{'cycle_prefix':'https://noaa-gefs-pds.s3.amazonaws.com/gefs.20260928/00/atmos/pgrb2sp25/','messages':6045,'messages_sha256':'0'*64,'missing':[]}})
        self.write('regions/test-region.json',{'cycle':self.CYCLE,'times':times,'members':31,'units':{'wind_speed_10m':'m/s','wind_gusts_10m':'m/s'},
                   'points':[{'latitude':35.5,'longitude':-121.5,'grid':[35.5,-121.5],'distance_km':0.0,'wind_speed_10m':wind,'wind_gusts_10m':gust},
                             {'latitude':35.0,'longitude':-121.0,'grid':None,'distance_km':None,'wind_speed_10m':series(0,[None]*3),'wind_gusts_10m':series(0,[None]*3)}]})

    def write(self,relative,value):
        path=self.root/'ncep_gefs025'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

    class Offline:
        def __init__(self):self.requests=[]
        def get(self,*a,**k):raise AssertionError('local build must be read without the network')

    def test_hourly_member_frames_keep_the_app_shape_and_record_receipts(self):
        from skippercast.pipeline.intelligence import ensemble
        client=self.Offline();data=ensemble(client,self.region)
        self.assertEqual((data['model'],data['expected_members'],data['native_step_hours'],data['api_step_hours']),('ncep_gefs025',31,3,1))
        self.assertEqual(data['issued_at'],'2026-09-27T00:00:00Z')
        self.assertTrue(data['upstream']['cycle_prefix'].startswith('https://noaa-gefs-pds.s3.amazonaws.com/'))
        self.assertNotIn('open-meteo',json.dumps(data))
        point,unsampled=data['points']
        self.assertEqual((point['point_id'],point['requested'],point['grid']),('a',[35.5,-121.5],[35.5,-121.5]))
        self.assertEqual([f['time'] for f in point['frames']],[self.CYCLE+h*3600 for h in range(7)])
        one=dict((m[0],m[1:]) for m in point['frames'][1]['members'])
        self.assertEqual(one[0],[1.9,4.5])  # 1 m/s and 2.33 m/s one hour into the 0->3 and 1->5 m/s steps
        self.assertNotIn(1,one)  # a missing native neighbour excludes the member, never fills it
        self.assertIsNone(one[2][1])  # gust below wind is inconsistent and dropped
        self.assertIn(1,dict((m[0],m) for m in point['frames'][0]['members']))
        self.assertEqual(len(point['frames'][1]['members']),30)
        self.assertEqual(unsampled['frames'],[])
        self.assertEqual([r['url'].rsplit('/',2)[-2:] for r in client.requests],[['ncep_gefs025','manifest.json'],['regions','test-region.json'],['ncep_gefs025','manifest.json']])
        self.assertTrue(all(len(r['sha256'])==64 for r in client.requests))

    def test_moved_points_and_wrong_member_counts_fail_closed(self):
        from skippercast.pipeline.intelligence import ensemble
        moved={**self.region,'forecast_points':[{**self.region['forecast_points'][0],'latitude':35.6},self.region['forecast_points'][1]]}
        with self.assertRaisesRegex(ValueError,'point mismatch'):ensemble(self.Offline(),moved)
        document=json.loads((self.root/'ncep_gefs025/regions/test-region.json').read_text());document['members']=30
        self.write('regions/test-region.json',document)
        with self.assertRaisesRegex(ValueError,'members or units'):ensemble(self.Offline(),self.region)

    def test_the_ensemble_source_no_longer_names_open_meteo(self):
        source=(ROOT/'src/skippercast/pipeline/intelligence.py').read_text()
        self.assertNotIn('open-meteo',source)


class ForecastCurrentsTests(unittest.TestCase):
    """The app's hourly surface current comes from the published WCOFS source, not Open-Meteo."""
    def test_nearest_cell_per_frame_within_one_and_a_half_grid_lengths(self):
        from skippercast.pipeline.intelligence import forecast_currents
        points=[{'id':'near','latitude':35.0,'longitude':-121.0},{'id':'far','latitude':36.0,'longitude':-121.0}]
        source={'name':'NOAA WCOFS surface currents','status':'ok','data':{'issued_at':'2026-09-28T03:00:00Z','valid_from':100,'valid_through':10900,'resolution_km':4,
                'source_url':'https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html',
                'frames':[{'time':100,'cells':[[35.03,-121.0,0.0,90.0],[35.01,-121.0,0.4,180.0]]},{'time':10900,'cells':[[35.2,-121.0,1.0,10.0]]}]}}
        out=forecast_currents(source,points)
        near,far=out['points']
        self.assertEqual(near['requested'],[35.0,-121.0])
        self.assertEqual(near['samples'],[[100,35.01,-121.0,0.4,180.0,1.11]])  # the second frame's cell is 22 km away: omitted, not filled
        self.assertEqual(far['samples'],[])
        self.assertEqual((out['status'],out['valid_through'],out['resolution_km']),('ok',10900,4))
        self.assertNotIn('open-meteo',json.dumps(out))

    def test_stale_or_failed_wcofs_publishes_no_samples(self):
        from skippercast.pipeline.intelligence import forecast_currents
        for status in ('retained','stale','failed'):
            out=forecast_currents({'status':status,'data':{'frames':[{'time':1,'cells':[[35,-121,1,1]]}],'resolution_km':4}},[{'id':'a','latitude':35,'longitude':-121}])
            self.assertEqual((out['status'],out['points']),(status,[]))
        self.assertEqual(forecast_currents(None,[])['status'],'missing')

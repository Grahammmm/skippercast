import base64
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from skippercast.pipeline.verification import forecast_records,merge_records,verify
from skippercast.pipeline.ocean import dap_arrays,vector,bounds_indices
ROOT=Path(__file__).resolve().parents[1]


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

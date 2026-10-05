"""Offline interpreted habitat admission, native masks and artifact identity."""
from copy import deepcopy
from datetime import timedelta
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from affine import Affine
import rasterio
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import classified_habitat as ch, publish, state_cache
from skippercast.seafloor.io import sha256
from skippercast.seafloor.screen import screen_candidates
from skippercast.seafloor.substrate import classify
from tests.gis.test_seafloor_screen import geo, state as raw_state
from tests._support import NOW


def state(exclusion=None):
    return json.loads(json.dumps(raw_state(exclusion)))


def policy():
    return {'id': 'fixture-rugose-v1', 'reviewed_on': '2026-09-01',
        'depth_source_id': 'native', 'depth_source_sha256': 'a'*64,
        'classification_source_id': 'classes', 'classification_source_sha256': 'b'*64,
        'metadata_url': 'https://example.test/original-metadata', 'metadata_sha256': 'c'*64,
        'rugose_raw_codes': [3,13], 'credit': 'Original publisher and mapping lab',
        'release_license': 'public-domain-us-gov', 'notice': 'Not for navigation.',
        'review_basis': 'Synthetic explicitly reviewed class3; mixed excluded.'}


def row():
    return {'id':'native','sha256':'a'*64,'status':'usable','kind':'bathymetry',
            'resolution_m':2.,'vertical_datum':'unknown','license':'public-domain-us-gov',
            'url':'https://example.test/original-depth','publisher':'Original publisher',
            'adapter_review':{'requested_bounds_wgs84':[-122,35,-121,36]}}


def binding():
    return {'row': {'id':'classes','sha256':'b'*64,'status':'candidate','kind':'substrate',
                   'format':'usgs-geotiff','license':'public-domain-us-gov',
                   'url':'https://example.test/original-class','publisher':'Original publisher'},
        'binding': {'source_id':'classes','source_sha256':'b'*64,'depth_source_ids':['native'],
                    'review_status':'reviewed','metadata_url':policy()['metadata_url'],
                    'metadata_sha256':'c'*64,'same_survey_as_depth':True,
                    'classes':{'1':{'normalized_code':1},'2':{'normalized_code':2},
                               '3':{'normalized_code':3},'13':{'normalized_code':3}}}}


def candidate():
    f=ch.features_for([box(0,0,50,50)],'fixture',policy(),row(),binding())['features'][0]
    return f


class ClassifiedTests(unittest.TestCase):
    def test_mask_excludes_invalid_mixed_unknown_and_uses_paired_depth(self):
        depth=np.array([[7.619,7.62,91.44,91.441,np.nan,30,30,30,30,30]])
        valid=np.ones(depth.shape,dtype=bool);valid[0,5]=False
        inside=np.ones(depth.shape,dtype=bool);inside[0,9]=False
        classes=classify(np.array([[3,13,3,3,3,3,1,2,0,3]]),
                         np.array([[1,1,1,1,1,1,1,1,0,1]],dtype=bool),binding()['binding'])
        self.assertEqual(ch.candidate_mask(depth,valid,classes,inside).tolist(),
                         [[False,True,True,False,False,False,False,False,False,False]])
        for raw in (np.array([[99]]),np.array([[3.1]])):
            with self.assertRaises(ValueError):classify(raw,np.ones(raw.shape,dtype=bool),binding()['binding'])

    def test_tile_dissolve_nodata_hole_baseline_difference_and_fine_depth_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'depth.tif';affine=Affine(2,0,0,0,-2,64)
            depth=np.full((32,32),30,dtype='float32');depth[6:8,6:8]=-9999
            depth[:4,:4]=81 # Producer coarse zone must be excluded.
            with rasterio.open(path,'w',driver='GTiff',width=32,height=32,count=1,
                               dtype='float32',crs='EPSG:3310',transform=affine,nodata=-9999) as dst:dst.write(depth,1)
            from contextlib import contextmanager
            @contextmanager
            def reader(*args,**kwargs):
                yield lambda w:np.full((int(w.height),int(w.width)),3,dtype='uint8')
            r=dict(row(),resolution_profile={'fine_to_depth_m':80})
            support=box(0,0,64,64);existing=box(0,0,8,64)
            with patch.object(ch,'class_reader',reader):
                a,sa=ch.extract(r,binding(),path,support,existing,root=tmp,edge=16)
                b,sb=ch.extract(r,binding(),path,support,existing,root=tmp,edge=32)
            aa,bb=unary_union(a),unary_union(b)
            self.assertTrue(aa.equals(bb));self.assertEqual(sa,sb)
            self.assertEqual(aa.intersection(existing).area,0)
            self.assertFalse(aa.covers(box(12,48,16,52)))
            self.assertEqual(len(aa.interiors),1)
            self.assertGreater(aa.area,1000)
            with self.assertRaisesRegex(ValueError,'bounded'):
                ch.extract(r,binding(),path,support,existing,root=tmp,max_pixels=10)

    def test_screen_contract_separate_credit_and_no_rank_spoofing(self):
        c=candidate();passed,held,summary=screen_candidates({'features':[c]},state())
        self.assertFalse(held['features']);p=passed['features'][0]['properties']
        self.assertTrue(ch.published_contract(p));self.assertEqual(p['source_ids'],['native','classes'])
        self.assertEqual((summary['habitat_count'],summary['tier2_km2'],summary['search_area_count']),(0,0,0))
        self.assertEqual(summary['classified_area_count'],1);self.assertAlmostEqual(summary['classified_area_km2'],.0025)
        self.assertEqual(passed['features'][0]['geometry'],c['geometry'])
        for change in ({'terrain':{'grade':'A'}},{'fit':{'lingcod':3}},
                       {'terrain':{'grade':'A'},'fit':{'lingcod':3}},
                       {'metric_support_fraction':.5,'rule_version':'seafloor-habitat-v1'},
                       {'detail_level':'ranked'},
                       {'metric_support_fraction':.5},{'terrain_grade':'A'},
                       {'source_ids':['native']},{'depth_max_ft':301},{'habitat_quality_hold':{'held':True}}):
            bad=deepcopy(c);bad['properties'].update(change)
            self.assertIsNone(ch.assessment(bad['properties']))
            self.assertFalse(screen_candidates({'features':[bad]},state())[0]['features'])
        for s in (state(geo(49,0)),state(geo(50,0)),
                  {'status':'held','reasons':['screen-missing'],'layers':[]},
                  {'status':'held','reasons':['screen-stale'],'layers':[]}):
            self.assertFalse(screen_candidates({'features':[c]},s)[0]['features'])
        twice=screen_candidates({'features':[c,c]},state())[2]
        self.assertEqual(twice['classified_area_km2'],summary['classified_area_km2'])

    def test_invalid_native_polygon_rejected_without_repair(self):
        from shapely.geometry import Polygon
        with self.assertRaisesRegex(ValueError,'Invalid classified polygon'):
            ch.features_for([Polygon([(0,0),(50,50),(0,50),(50,0),(0,0)])],
                            'fixture',policy(),row(),binding())

    def test_real_source_context_current_original_review_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'var/seafloor/reaches/fixture';folder.mkdir(parents=True)
            r=row();b=binding();p=policy()
            atomic_json(root/'catalog/habitat-rules.json',{'substrate_bindings':[b['binding']]})
            atomic_json(folder/'cells.json',{'cells':[{'id':'3310:0:0','tier':1,'source_id':'native'}]})
            atomic_json(folder/'candidates.geojson',{'features':[]})
            physical={'input_hash':'baseline','outputs':{n:sha256(folder/n) for n in ('cells.json','candidates.geojson')}}
            atomic_json(folder/'physical.json',physical)
            run={'physical_input_hash':'baseline','inputs':{'reach_id':'fixture','sources':[r],
                 'substrate_bindings':{'native':b}},'outputs':{n:sha256(folder/n) for n in
                 ('cells.json','candidates.geojson','physical.json')}}
            atomic_json(folder/'run.json',run)
            cache=root/'var/seafloor/cache'/r['sha256'];cache.mkdir(parents=True)
            cog=cache/('d'*64+'.tif');cog.write_bytes(b'synthetic normalized bytes')
            receipt={'cog_sha256':sha256(cog)};atomic_json(cog.with_suffix('.json'),receipt)
            manifest={'surveys':[r,b['row']]}
            with patch.object(ch,'load_manifest',return_value=manifest),patch.object(ch,'verify_sources'), \
                 patch.object(ch,'ingest',return_value=(receipt,None,None)),patch.object(ch,'verify_review'):
                ident,*_=ch.source_context(root,'fixture',p)
                self.assertEqual(ident['normalized_sha256'],sha256(cog))
                for owner,key,value in [(r,'status','withdrawn'),(r,'habitat_quality_hold',{'held':True}),
                    (b['row'],'status','withdrawn'),(b['row'],'habitat_quality_dependencies',['held']),
                    (b['row'],'license','unknown'),(b['binding'],'metadata_sha256','e'*64),
                    (b['binding'],'classes',{'3':{'normalized_code':2},'13':{'normalized_code':3}})]:
                    old=deepcopy(owner);owner[key]=value
                    atomic_json(root/'catalog/habitat-rules.json',{'substrate_bindings':[b['binding']]})
                    with self.subTest(key=key,value=value), self.assertRaises(ValueError):ch.source_context(root,'fixture',p)
                    owner.clear();owner.update(old)
                    atomic_json(root/'catalog/habitat-rules.json',{'substrate_bindings':[b['binding']]})
                cog.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError,'normalized bytes'):ch.source_context(root,'fixture',p)

    def test_stage_and_publisher_reject_tampering_replay_policy_and_current_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'var/seafloor/reaches/fixture';folder.mkdir(parents=True)
            p=policy();context=({'policy':p,'depth_source':row(),'classification_binding':binding()},
                row(),binding(),None,box(0,0,250,250),box(300,300,400,400),
                [{'source_id':'native','license':'public-domain-us-gov','attribution':p['credit'],'notice':p['notice']}])
            atomic_json(folder/'run.json',{'inputs':{'sources':[row()]}})
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            with patch.object(ch,'source_context',return_value=context), \
                 patch.object(ch,'extract',return_value=([box(0,0,50,50)],{'class3_valid_depth_pixels':625,'classified_selected_area_km2':.0025})), \
                 patch('skippercast.seafloor.screen.load_snapshot',return_value=state()):
                first=ch.stage('fixture',root=root)
                self.assertFalse(first['physical_reused'])
                selected,receipt=ch.publication_features('fixture',root=root)
                self.assertEqual(len(selected),1);self.assertEqual(receipt['summary']['classified_area_count'],1)
                self.assertEqual(selected[0]['properties']['source_rights'][0]['attribution'],p['credit'])
                self.assertTrue(ch.stage('fixture',root=root)['physical_reused'])
                for name in ('classified-candidates.geojson','classified-native.geojson','classified-habitat.geojson','classified-held.geojson'):
                    path=folder/name;saved=path.read_bytes();path.write_bytes(b'{}')
                    with self.assertRaisesRegex(ValueError,'output hash'):ch.publication_features('fixture',root=root)
                    path.write_bytes(saved)
                native_path=folder/'classified-native.geojson'
                saved_native=native_path.read_bytes();native_path.unlink()
                with self.assertRaises(FileNotFoundError):ch.publication_features('fixture',root=root)
                native_path.write_bytes(saved_native)
                # An older representation receipt must restage its classified
                # inventory, while the graded baseline stays unchanged.
                path=folder/'classified-run.json';r=read_json(path)
                r['physical_input_hash']='older-representation';atomic_json(path,r)
                self.assertFalse(ch.stage('fixture',root=root)['physical_reused'])
                path=folder/'classified-run.json';saved=path.read_bytes();r=read_json(path);r['reach']='other';atomic_json(path,r)
                with self.assertRaisesRegex(ValueError,'identity'):ch.publication_features('fixture',root=root)
                path.write_bytes(saved)
                with patch('skippercast.seafloor.screen.load_snapshot',return_value={'status':'held','reasons':['screen-stale'],'layers':[]}):
                    with self.assertRaisesRegex(ValueError,'inputs changed'):ch.publication_features('fixture',root=root)
                atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[]})
                with self.assertRaisesRegex(ValueError,'withdrawn'):ch.publication_features('fixture',root=root)
                before_baseline=(folder/'run.json').read_bytes()
                withdrawn=ch.stage('fixture',root=root)
                self.assertEqual(withdrawn['physical_summary']['candidate_count'],0)
                self.assertEqual(ch.publication_features('fixture',root=root)[0],[])
                self.assertEqual((folder/'run.json').read_bytes(),before_baseline)
            for name in ('classified-run.json','classified-candidates.geojson','classified-native.geojson','classified-habitat.geojson','classified-held.geojson'):
                self.assertTrue(state_cache.allowed('fixture',f'reaches/fixture/{name}'))
            self.assertFalse(state_cache.allowed('fixture','reaches/other/classified-run.json'))

    def test_archive_includes_classified_but_canonical_fishing_export_excludes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            c=screen_candidates({'features':[candidate()]},state())[0]['features'][0]
            c['properties']['source_rights']=[]
            layers={'cells':[],'habitat':[dict(c,properties=publish.flat_properties(c['properties']))]}
            atomic_json(root/'dist/data/seafloor-ledger.json',{'reaches':[],'reference':{}})
            atomic_json(root/'catalog/surveys.json',{'surveys':[]})
            seen={}
            def archive(tool,value,path,**kwargs):
                seen.update(value);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'PMTilesfixture')
            with patch.object(publish,'region_layers',return_value=(layers,{},NOW+timedelta(days=1))), \
                 patch('scripts.build_map_tiles.build_vector_archive',side_effect=archive):
                folder,manifest=publish.build('fixture',root=root,tool='fixture',now=NOW)
            self.assertEqual(len(seen['habitat']),1)
            self.assertEqual(manifest['habitat_counts']['classified-area'],1)
            self.assertEqual(json.loads(gzip.decompress((folder/manifest['export_file']).read_bytes()))['features'],[])

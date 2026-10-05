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
from shapely.geometry import Point, Polygon, box, mapping, shape
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


def neighbor_fixture(root):
    """Synthetic shared reference grid, pinned by a normal baseline identity."""
    root=Path(root);reference=root/'var/seafloor/reference';reference.mkdir(parents=True)
    catalog={'input_hash':'planning-v1','reaches':[{'id':'fixture'},{'id':'neighbor'}]}
    atomic_json(root/'catalog/reaches.json',catalog)
    grid={'input_hash':'planning-v1','cells':[{'id':'3310:0:0','reach':'fixture'},
                                           {'id':'3310:1:0','reach':'neighbor'}]}
    atomic_json(reference/'cells.json',grid)
    atomic_json(reference/'run.json',{'input_hash':'planning-v1',
        'output_hashes':{'cells.json':sha256(reference/'cells.json')}})
    inputs={'reach_id':'fixture','sources':[row()],
            'reference_cells_sha256':sha256(reference/'cells.json'),
            'reaches_sha256':sha256(root/'catalog/reaches.json')}
    baseline={'inputs':inputs,'physical_input_hash':ch.digest(inputs)}
    atomic_json(root/'var/seafloor/reaches/fixture/run.json',baseline)
    return baseline


class ClassifiedTests(unittest.TestCase):
    def test_stage_deduplicates_later_pair_against_prior_native_union_and_versions_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'var/seafloor/reaches/fixture';folder.mkdir(parents=True)
            first=dict(policy(),id='first-pair',depth_source_id='native-a')
            second=dict(policy(),id='second-pair',depth_source_id='native-b')
            rows=[dict(row(),id='native-a'),dict(row(),id='native-b',sha256='d'*64)]
            bindings=[binding(),dict(binding(),row=dict(binding()['row'],id='classes-b',sha256='e'*64),
                binding=dict(binding()['binding'],source_id='classes-b',source_sha256='e'*64))]
            source_shapes={'native-a':Polygon(box(0,0,100,100).exterior.coords,
                                                [box(20,20,80,80).exterior.coords]),
                           'native-b':box(50,0,150,100)}
            atomic_json(folder/'run.json',{'inputs':{'sources':rows}})
            contexts=[]
            for p,r,b in zip((first,second),rows,bindings):
                identity={'policy':p,'depth_source':r,'classification_binding':b}
                contexts.append((identity,r,b,None,box(0,0,200,200),box(180,180,190,190),[]))
            # Old stage behavior gave both pairs only the same graded baseline;
            # this control must reproduce the positive duplicate-area failure.
            old_later,_=ch.additional_patches([source_shapes['native-b']],
                contexts[1][4],contexts[1][5])
            self.assertGreater(unary_union(old_later).intersection(source_shapes['native-a']).area,0)
            existing_seen=[]

            def extract_with_native_difference(r,b,path,support,existing,**kwargs):
                existing_seen.append(existing)
                patches,classified=ch.additional_patches([source_shapes[r['id']]],support,existing)
                return patches,{'class3_valid_depth_pixels':1,
                    'classified_selected_area_km2':classified.area/1_000_000}

            empty={'type':'FeatureCollection','features':[]}
            policy_rows=[first,second]
            def hold_every_candidate(candidates,*args,**kwargs):
                return empty,candidates,{'held_count':len(candidates['features'])}
            context_by_id={p['id']:c for p,c in zip((first,second),contexts)}
            with patch.object(ch,'policies',return_value=policy_rows), \
                 patch.object(ch,'source_context',side_effect=lambda _root,_reach,p,**kwargs:context_by_id[p['id']]), \
                 patch.object(ch,'extract',side_effect=extract_with_native_difference) as extract_mock, \
                 patch('skippercast.seafloor.screen.load_snapshot',return_value=state()), \
                 patch('skippercast.seafloor.screen.input_identity',return_value={'screen':'fixture'}), \
                 patch.object(ch,'classified_screen',side_effect=hold_every_candidate):
                staged=ch.stage('fixture',root=root)
                native=read_json(folder/'classified-native.geojson')['features']
                candidates=read_json(folder/'classified-candidates.geojson')['features']
                held=read_json(folder/'classified-held.geojson')['features']
                self.assertEqual(staged['physical_summary']['candidate_count'],3)
                self.assertEqual(len(held),3)  # Holds do not restore duplicate physical patches.
                self.assertEqual(read_json(folder/'classified-habitat.geojson')['features'],[])
                self.assertTrue(candidates[0]['properties']['id'].startswith('classified-fixture-first-pair-'))
                self.assertTrue(all(shape(f['geometry']).area >= 1000 for f in native))
                geometries=[shape(f['geometry']) for f in native]
                self.assertEqual(unary_union(geometries).area,13200)
                self.assertEqual(sum(g.area for g in geometries),13200)
                self.assertTrue(geometries[0].interiors)  # Earlier native hole is retained.
                self.assertEqual(geometries[1].intersection(geometries[0]).area,0)
                self.assertEqual(geometries[2].intersection(geometries[0]).area,0)
                self.assertEqual(len(existing_seen),2)
                self.assertTrue(existing_seen[1].contains(Point(10,10)))
                self.assertFalse(existing_seen[1].contains(Point(50,50)))  # Prior hole remains open.
                dedup=staged['inputs']['physical'].get('native_pair_dedup')
                self.assertEqual(dedup,{'version':ch.NATIVE_PAIR_DEDUP_VERSION,
                    'policy_order':['first-pair','second-pair'],
                    'existing_geometry':'graded-baseline-plus-earlier-original-native-patches'})
                # The next run must reuse without calling the extractor again.
                cached=ch.stage('fixture',root=root)
                self.assertTrue(cached['physical_reused'])
                self.assertEqual(extract_mock.call_count,2)
                stable_native=(folder/'classified-native.geojson').read_bytes()
                stable_candidates=(folder/'classified-candidates.geojson').read_bytes()
                self.assertEqual(ch.publication_features('fixture',root=root)[0],[])
                receipt_path=folder/'classified-run.json';receipt=read_json(receipt_path)
                receipt['inputs']['physical'].pop('native_pair_dedup')
                receipt['physical_input_hash']=ch.digest(receipt['inputs']['physical'])
                receipt['input_hash']=ch.digest(receipt['inputs'])
                atomic_json(receipt_path,receipt)
                with self.assertRaisesRegex(ValueError,'inputs changed'):
                    ch.publication_features('fixture',root=root)
                rebuilt=ch.stage('fixture',root=root)
                self.assertFalse(rebuilt['physical_reused'])
                self.assertEqual(extract_mock.call_count,4)
                self.assertEqual((folder/'classified-native.geojson').read_bytes(),stable_native)
                self.assertEqual((folder/'classified-candidates.geojson').read_bytes(),stable_candidates)
                policy_rows.reverse()
                with self.assertRaisesRegex(ValueError,'source-pair order changed'):
                    ch.publication_features('fixture',root=root)
                reordered=ch.stage('fixture',root=root)
                self.assertFalse(reordered['physical_reused'])
                self.assertEqual(extract_mock.call_count,6)
                self.assertEqual(reordered['inputs']['physical']['native_pair_dedup']['policy_order'],
                                 ['second-pair','first-pair'])
                reordered_candidates=read_json(folder/'classified-candidates.geojson')['features']
                self.assertTrue(reordered_candidates[0]['properties']['id'].startswith(
                    'classified-fixture-second-pair-'))

                # Even a coherently rehashed receipt cannot restore duplicate
                # area. Include held native patches and keep the current marker.
                forged_candidates={'type':'FeatureCollection','features':[]}
                forged_native={'version':ch.GEOMETRY_VERSION,'crs':'EPSG:3310','features':[]}
                for p,r,b in zip((first,second),rows,bindings):
                    g=source_shapes[r['id']]
                    f=ch.features_for([g],'fixture',p,r,b)['features'][0]
                    forged_candidates['features'].append(f)
                    forged_native['features'].append({'type':'Feature',
                        'properties':{'id':f['properties']['id']},'geometry':mapping(g)})
                for name,obj in [('classified-candidates.geojson',forged_candidates),
                                 ('classified-native.geojson',forged_native),
                                 ('classified-habitat.geojson',empty),
                                 ('classified-held.geojson',forged_candidates)]:
                    atomic_json(folder/name,obj)
                receipt=read_json(receipt_path)
                receipt['representation']=ch.verify_inventory(forged_candidates,forged_native)
                receipt['summary']={'held_count':2}
                receipt['physical_summary']['candidate_count']=2
                receipt['outputs']={name:ch.sha256(folder/name) for name in receipt['outputs']}
                atomic_json(receipt_path,receipt)
                with self.assertRaisesRegex(ValueError,'native habitat overlap'):
                    ch.publication_features('fixture',root=root)
                with self.assertRaisesRegex(ValueError,'native habitat overlap'):
                    ch.stage('fixture',root=root)
                self.assertEqual(extract_mock.call_count,6)  # Reject cached geometry, no pixels.

                unknown=deepcopy(forged_candidates)
                unknown['features'][0]['properties']['classified_area']['policy_id']='unknown'
                with self.assertRaisesRegex(ValueError,'Unreviewed classified native'):
                    ch.verify_pair_disjointness(unknown,forged_native,contexts)

    def test_single_pair_outputs_and_cache_behavior_remain_unduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'var/seafloor/reaches/fixture';folder.mkdir(parents=True)
            p=policy();r=row();b=binding();atomic_json(folder/'run.json',{'inputs':{'sources':[r]}})
            identity={'policy':p,'depth_source':r,'classification_binding':b}
            context=(identity,r,b,None,box(0,0,100,100),box(180,180,190,190),[])
            empty={'type':'FeatureCollection','features':[]}
            patch_geometry=box(0,0,50,50)
            with patch.object(ch,'policies',return_value=[p]), \
                 patch.object(ch,'source_context',return_value=context), \
                 patch.object(ch,'extract',return_value=([patch_geometry],
                    {'class3_valid_depth_pixels':625,'classified_selected_area_km2':.0025})) as extract_mock, \
                 patch('skippercast.seafloor.screen.load_snapshot',return_value=state()), \
                 patch('skippercast.seafloor.screen.input_identity',return_value={'screen':'fixture'}), \
                 patch.object(ch,'classified_screen',return_value=(empty,empty,{})):
                first=ch.stage('fixture',root=root)
                native_before=(folder/'classified-native.geojson').read_bytes()
                self.assertNotIn('native_pair_dedup',first['inputs']['physical'])
                second=ch.stage('fixture',root=root)
                self.assertTrue(second['physical_reused'])
                self.assertEqual((folder/'classified-native.geojson').read_bytes(),native_before)
                self.assertEqual(extract_mock.call_count,1)

    def test_neighbor_planning_missing_changed_or_shrunk_reference_fails_closed(self):
        self.assertEqual(ch.neighbor_planning('/nonexistent','fixture',policy()),(None,None))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);baseline=neighbor_fixture(root)
            p=dict(policy(),reach_ids=['fixture'],neighbor_reaches=['neighbor'])
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            self.assertEqual(ch.policies(root)[0],p)
            meta,mask=ch.neighbor_planning(root,'fixture',p)
            self.assertEqual(meta['planning_cell_count'],1)
            self.assertTrue(mask.intersects(box(245,0,250,50)))
            self.assertFalse(mask.intersects(box(0,0,50,50)))
            for neighbors in ([],['unknown'],['fixture'],['neighbor','neighbor'],'neighbor'):
                with self.subTest(neighbors=neighbors),self.assertRaises(ValueError):
                    ch.neighbor_planning(root,'fixture',dict(p,neighbor_reaches=neighbors))
                atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,
                    'sources':[dict(p,neighbor_reaches=neighbors)]})
                with self.assertRaises(ValueError):ch.policies(root)
            grid=root/'var/seafloor/reference/cells.json';original=grid.read_bytes();grid.unlink()
            with self.assertRaises(FileNotFoundError):ch.neighbor_planning(root,'fixture',p)
            grid.write_bytes(original)
            # Rehashing a smaller reference receipt cannot override the pinned
            # normal baseline's original grid or physical input identity.
            data=read_json(grid);data['cells']=data['cells'][:1];atomic_json(grid,data)
            receipt=root/'var/seafloor/reference/run.json';saved=receipt.read_bytes()
            changed=read_json(receipt);changed['output_hashes']['cells.json']=sha256(grid);atomic_json(receipt,changed)
            with self.assertRaisesRegex(ValueError,'reference identity'):ch.neighbor_planning(root,'fixture',p)
            baseline['inputs']['reference_cells_sha256']=sha256(grid)
            atomic_json(root/'var/seafloor/reaches/fixture/run.json',baseline)
            with self.assertRaisesRegex(ValueError,'physical identity'):ch.neighbor_planning(root,'fixture',p)
            baseline['physical_input_hash']=ch.digest(baseline['inputs'])
            atomic_json(root/'var/seafloor/reaches/fixture/run.json',baseline)
            with self.assertRaisesRegex(ValueError,'missing or duplicated'):ch.neighbor_planning(root,'fixture',p)
            grid.write_bytes(original);receipt.write_bytes(saved)
            neighbor_fixture_baseline={'inputs':dict(baseline['inputs'],reference_cells_sha256=sha256(grid))}
            neighbor_fixture_baseline['physical_input_hash']=ch.digest(neighbor_fixture_baseline['inputs'])
            atomic_json(root/'var/seafloor/reaches/fixture/run.json',neighbor_fixture_baseline)
            catalog=read_json(root/'catalog/reaches.json');catalog['input_hash']='stale-planning'
            atomic_json(root/'catalog/reaches.json',catalog)
            with self.assertRaisesRegex(ValueError,'reference identity'):ch.neighbor_planning(root,'fixture',p)

    def test_neighbor_native_hold_is_whole_patch_and_rechecked_after_forged_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);neighbor_fixture(root);folder=root/'var/seafloor/reaches/fixture'
            p=dict(policy(),reach_ids=['fixture'],neighbor_reaches=['neighbor'])
            metadata,_=ch.neighbor_planning(root,'fixture',p)
            context=({'policy':p,'depth_source':row(),'classification_binding':binding(),
                      'neighbor_planning':metadata},row(),binding(),None,box(0,0,500,250),
                     box(600,600,700,700),[])
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            patches=[box(0,0,50,50),box(245,0,295,50)]
            with patch.object(ch,'source_context',return_value=context), \
                 patch.object(ch,'extract',return_value=(patches,{'class3_valid_depth_pixels':1250,
                     'classified_selected_area_km2':.005})), \
                 patch('skippercast.seafloor.screen.load_snapshot',return_value=state()):
                first=ch.stage('fixture',root=root)
                self.assertEqual(first['physical_summary']['candidate_count'],2)
                self.assertEqual(first['summary']['classified_area_count'],1)
                self.assertEqual(first['summary']['held_by_reason'],{'overlap-neighbor-planning':1})
                native=read_json(folder/'classified-native.geojson')
                held=read_json(folder/'classified-held.geojson')['features'][0]
                self.assertEqual(shape(native['features'][1]['geometry']).area,2500)
                self.assertEqual(held['properties']['area_ha'],.25)
                self.assertFalse(held['properties']['exportable'])
                self.assertEqual(len(ch.publication_features('fixture',root=root)[0]),1)
                candidates=read_json(folder/'classified-candidates.geojson')
                geometries={f['properties']['id']:f['geometry'] for f in native['features']}
                # Forge coherent screen outputs and hashes by omitting the
                # native planning mask. Admission must reconstruct the hold.
                habitat,omitted_held,summary=screen_candidates(candidates,state(),native_geometries=geometries)
                atomic_json(folder/'classified-habitat.geojson',habitat)
                atomic_json(folder/'classified-held.geojson',omitted_held)
                receipt=read_json(folder/'classified-run.json');receipt['summary']=summary
                receipt['outputs']={n:sha256(folder/n) for n in receipt['outputs']}
                atomic_json(folder/'classified-run.json',receipt)
                with self.assertRaisesRegex(ValueError,'whole-polygon screen changed'):
                    ch.publication_features('fixture',root=root)
            with self.assertRaisesRegex(ValueError,'original native geometry'):
                screen_candidates({'features':[]},state(),native_exclusions={})

    def test_policy_support_modes_are_versioned_and_reach_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'catalog').mkdir()
            p=policy()
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            self.assertEqual(ch.support_mode(ch.policies(root)[0]),ch.SELECTED_SOURCE_SUPPORT)
            # Legacy unscoped policy does not depend on the new reach inventory.
            atomic_json(root/'catalog/reaches.json',{'reaches':[{'id':'fixture-r01'}, {'id':'fixture-r02'}]})
            p['reach_ids']=['fixture-r01']  # Optional scope is also valid for legacy behavior.
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            self.assertTrue(ch.policy_applies_to_reach(ch.policies(root)[0],'fixture-r01'))
            self.assertFalse(ch.policy_applies_to_reach(ch.policies(root)[0],'fixture-r02'))
            p['support_mode']=ch.PAIRED_REFERENCE_SUPPORT
            p.pop('reach_ids')
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            with self.assertRaisesRegex(ValueError,'requires reviewed reach_ids'):ch.policies(root)
            p['reach_ids']=['not-a-real-reach']
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            with self.assertRaisesRegex(ValueError,'reach scope'):ch.policies(root)
            p['reach_ids']=[{'id':'fixture-r01'}]
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            with self.assertRaisesRegex(ValueError,'reach scope'):ch.policies(root)
            p['reach_ids']=['fixture-r01']
            p['support_mode']='unversioned-mode'
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            with self.assertRaisesRegex(ValueError,'Unknown classified habitat support mode'):ch.policies(root)

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
            depth[:4,10:14]=81 # Producer coarse zone must be excluded outside baseline geometry.
            depth[4:8,10:14]=80 # Exact producer transition is coarse and excluded too.
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
            self.assertFalse(aa.covers(box(20,56,28,64)))
            self.assertFalse(aa.covers(box(20,48,28,56)))
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
            other=dict(r,id='other',sha256='f'*64)
            atomic_json(root/'catalog/habitat-rules.json',{'substrate_bindings':[b['binding']]})
            atomic_json(root/'catalog/reaches.json',{'reaches':[{'id':'fixture'}]})
            cells=[{'id':'3310:0:0','tier':1,'source_id':'native'},
                   {'id':'3310:1:0','tier':1,'source_id':'other'},
                   {'id':'3310:2:0','tier':0,'source_id':'other'},
                   {'id':'3310:3:0','tier':True,'source_id':'other'}]
            atomic_json(folder/'cells.json',{'cells':cells})
            atomic_json(folder/'candidates.geojson',{'features':[]})
            physical={'input_hash':'baseline','outputs':{n:sha256(folder/n) for n in ('cells.json','candidates.geojson')}}
            atomic_json(folder/'physical.json',physical)
            run={'physical_input_hash':'baseline','inputs':{'reach_id':'fixture','sources':[r,other],
                 'substrate_bindings':{'native':b}},'outputs':{n:sha256(folder/n) for n in
                 ('cells.json','candidates.geojson','physical.json')}}
            atomic_json(folder/'run.json',run)
            cache=root/'var/seafloor/cache'/r['sha256'];cache.mkdir(parents=True)
            cog=cache/('d'*64+'.tif');cog.write_bytes(b'synthetic normalized bytes')
            receipt={'cog_sha256':sha256(cog)};atomic_json(cog.with_suffix('.json'),receipt)
            other_cache=root/'var/seafloor/cache'/other['sha256'];other_cache.mkdir()
            other_cog=other_cache/('e'*64+'.tif');other_cog.write_bytes(b'other synthetic normalized bytes')
            other_receipt={'cog_sha256':sha256(other_cog)}
            atomic_json(other_cog.with_suffix('.json'),other_receipt)
            manifest={'surveys':[r,b['row'],other]}
            with patch.object(ch,'load_manifest',return_value=manifest),patch.object(ch,'verify_sources'), \
                 patch.object(ch,'ingest',side_effect=lambda source,*a,**kw:
                     (other_receipt if source['id']=='other' else receipt,None,None)), \
                 patch.object(ch,'verify_review'):
                ident,*_,legacy_support,_,_=ch.source_context(root,'fixture',p)
                self.assertEqual(ident['normalized_sha256'],sha256(cog))
                self.assertEqual(ch.support_mode(p),ch.SELECTED_SOURCE_SUPPORT)
                self.assertTrue(legacy_support.equals(box(0,0,250,250)))
                scoped=dict(p,reach_ids=['fixture'])
                ident,*_,legacy_scoped,_,_=ch.source_context(root,'fixture',scoped)
                self.assertTrue(legacy_scoped.equals(legacy_support))
                pair=dict(p,support_mode=ch.PAIRED_REFERENCE_SUPPORT,reach_ids=['fixture'])
                ident,*_,paired_support,_,_=ch.source_context(root,'fixture',pair)
                self.assertTrue(paired_support.equals(box(0,0,500,250)))
                self.assertEqual(ident['support_mode'],ch.PAIRED_REFERENCE_SUPPORT)
                with self.assertRaisesRegex(ValueError,'does not include requested reach'):
                    ch.source_context(root,'fixture',dict(pair,reach_ids=['other-reach']))
                # With no target-source winning cells, legacy is empty while
                # paired mode uses only the current eligible Tier 1 reference cell.
                cells=[{'id':'3310:1:0','tier':1,'source_id':'other'},
                       {'id':'3310:2:0','tier':0,'source_id':'other'}]
                atomic_json(folder/'cells.json',{'cells':cells})
                physical=read_json(folder/'physical.json');physical['outputs']['cells.json']=sha256(folder/'cells.json')
                atomic_json(folder/'physical.json',physical)
                run=read_json(folder/'run.json');run['outputs']['cells.json']=sha256(folder/'cells.json')
                run['outputs']['physical.json']=sha256(folder/'physical.json');atomic_json(folder/'run.json',run)
                _,*_,legacy_empty,_,_=ch.source_context(root,'fixture',p)
                _,*_,paired_positive,_,_=ch.source_context(root,'fixture',pair)
                self.assertTrue(legacy_empty.is_empty)
                self.assertTrue(paired_positive.equals(box(250,0,500,250)))
                # Tier 1 references must still be current manifest inputs with
                # usable bathymetry and approved rights at every identity check.
                original_other=deepcopy(other)
                for mutation in ('missing','withdrawn','changed_hash'):
                    with self.subTest(reference_mutation=mutation):
                        if mutation == 'missing':
                            manifest['surveys']=[r,b['row']]
                        else:
                            altered=deepcopy(original_other)
                            if mutation == 'withdrawn': altered['status']='withdrawn'
                            else: altered['sha256']='e'*64
                            manifest['surveys']=[r,b['row'],altered]
                        with self.assertRaises(ValueError):
                            ch.source_context(root,'fixture',pair)
                manifest['surveys']=[r,b['row'],original_other]
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

    def test_terrain_reference_checks_native_dependencies_rights_and_role_provenance(self):
        from shutil import copyfile
        from skippercast.seafloor import rights
        from skippercast.seafloor.normalized import raster_identity
        from tests.gis.test_seafloor_terrain_support import native_fixture
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'var/seafloor/reaches/fixture';folder.mkdir(parents=True)
            with native_fixture(root) as (reference_source,_,_):
                ref=reference_source['row'];ref.update(id='reference',sha256='f'*64,status='usable',
                    license=rights.CSUMB_LICENSE,publisher='CSUMB SFML',
                    url='https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/fixture.tar.gz')
                ref['terrain_support'].update(depth_source_id=ref['id'],source_sha256=ref['sha256'])
                ref['adapter_review'].update(source_sha256=ref['sha256'],
                    requested_bounds_wgs84=[-122,35,-121,36],native_resolution_m=[2,2],
                    vertical_datum='unknown',valid_pixels_in_requested_bounds=160000,
                    nominal_0_300ft_pixels_in_requested_bounds=160000,
                    raster_identity=raster_identity(reference_source['path']))
                ref['rights_review']={'policy_url':rights.CSUMB_POLICY,'source_sha256':ref['sha256'],
                    'producer':'CSUMB SFML','allowed_use':'noncommercial','attribution':rights.CSUMB_CREDIT,
                    'navigation_use':False,'for_profit_permission':'required-not-obtained','reviewed_on':'2026-01-01'}
                r=row();b=binding();p=dict(policy(),support_mode=ch.PAIRED_REFERENCE_SUPPORT,reach_ids=['fixture'])
                atomic_json(root/'deployments/production.json',{'source_use':'noncommercial','monetization':'none'})
                atomic_json(root/'catalog/habitat-rules.json',{'substrate_bindings':[b['binding']]})
                atomic_json(root/'catalog/reaches.json',{'reaches':[{'id':'fixture'}]})
                atomic_json(folder/'cells.json',{'cells':[{'id':'3310:0:0','tier':1,'source_id':ref['id']}]})
                atomic_json(folder/'candidates.geojson',{'features':[]})
                physical={'input_hash':'baseline','outputs':{n:sha256(folder/n) for n in ('cells.json','candidates.geojson')}}
                atomic_json(folder/'physical.json',physical)
                run={'physical_input_hash':'baseline','inputs':{'reach_id':'fixture','sources':[r,deepcopy(ref)],
                    'substrate_bindings':{'native':b}},'outputs':{n:sha256(folder/n) for n in
                    ('cells.json','candidates.geojson','physical.json')}}
                atomic_json(folder/'run.json',run)
                paths={};receipts={}
                for source in (r,ref):
                    cache=root/'var/seafloor/cache'/source['sha256'];cache.mkdir(parents=True)
                    path=cache/('d'*64+'.tif')
                    if source is ref:copyfile(reference_source['path'],path)
                    else:path.write_bytes(b'synthetic original pair normalized bytes')
                    rec=dict(source['adapter_review'],cog_sha256=sha256(path));atomic_json(path.with_suffix('.json'),rec)
                    paths[source['id']]=path;receipts[source['id']]=rec
                manifest={'surveys':[r,b['row'],ref]}
                with patch.object(ch,'load_manifest',return_value=manifest),patch.object(ch,'verify_sources'), \
                     patch.object(ch,'ingest',side_effect=lambda source,*a,**kw:(receipts[source['id']],None,None)), \
                     patch.object(ch,'verify_review'):
                    context=ch.source_context(root,'fixture',p);ident=context[0]
                    self.assertTrue(context[4].equals(box(0,0,250,250)))
                    evidence=ident['reference_support']
                    self.assertEqual(evidence['source_ids'],['reference'])
                    self.assertEqual(evidence['sources'][0]['normalized_sha256'],sha256(paths['reference']))
                    self.assertIsNotNone(evidence['sources'][0]['terrain_binding_sha256'])
                    declared={right['source_id']:right for right in context[-1]}
                    self.assertEqual(declared['reference']['license'],rights.CSUMB_LICENSE)
                    self.assertEqual(declared['reference']['attribution'],rights.CSUMB_CREDIT)
                    self.assertEqual(declared['reference']['commercial_use'],'permission-required')
                    feature=ch.features_for([box(0,0,50,50)],'fixture',p,r,b,
                        reference_support=evidence)['features'][0]
                    self.assertEqual(feature['properties']['source_ids'],['native','classes'])
                    self.assertEqual(json.loads(publish.flat_properties(feature['properties'])['reference_support']),evidence)
                    self.assertEqual(feature['properties']['classified_area']['new_measured_area_km2'],0)
                    # Cache-hit normalized bytes and original embedded metadata
                    # are actual dependencies, even though no roughness pixels
                    # are used as habitat evidence from this reference source.
                    metadata=root/'original-class/metadata.xml';original=metadata.read_bytes()
                    metadata.write_bytes(b'changed original reference metadata')
                    with self.assertRaisesRegex(ValueError,'metadata checksum'):ch.source_context(root,'fixture',p)
                    metadata.write_bytes(original)
                    normalized=paths['reference'];original=normalized.read_bytes();normalized.write_bytes(b'changed reference cache')
                    with self.assertRaisesRegex(ValueError,'normalized bytes'):ch.source_context(root,'fixture',p)
                    normalized.write_bytes(original)
                    receipt_path=normalized.with_suffix('.json');saved_receipt=receipt_path.read_bytes()
                    receipt_path.unlink()
                    with self.assertRaisesRegex(ValueError,'normalized bytes'):ch.source_context(root,'fixture',p)
                    receipt_path.write_bytes(saved_receipt)
                    profile=root/'deployments/production.json'
                    for setting in ({'source_use':'for-profit','monetization':'paid'},None):
                        if setting is None:profile.unlink()
                        else:atomic_json(profile,setting)
                        with self.assertRaisesRegex(ValueError,'For-profit'):ch.source_context(root,'fixture',p)
                    atomic_json(profile,{'source_use':'noncommercial','monetization':'none'})
                    old=deepcopy(ref['rights_review']);ref['rights_review']['source_sha256']='e'*64
                    # Preserve saved-row equality: the producer-rights gate must
                    # still reject a matching but unqualified input inventory.
                    run['inputs']['sources'][1]=deepcopy(ref);atomic_json(folder/'run.json',run)
                    with self.assertRaisesRegex(ValueError,'publication rights'):ch.source_context(root,'fixture',p)
                    ref['rights_review']=old;run['inputs']['sources'][1]=deepcopy(ref);atomic_json(folder/'run.json',run)
                    saved_binding=deepcopy(ref['terrain_support']);ref['terrain_support']['source_sha256']='e'*64
                    run['inputs']['sources'][1]=deepcopy(ref);atomic_json(folder/'run.json',run)
                    with self.assertRaisesRegex(ValueError,'exact reviewed native depth'):ch.source_context(root,'fixture',p)
                    ref['terrain_support']=saved_binding

    def test_publisher_rejects_forged_reference_role_even_with_rehashed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'var/seafloor/reaches/fixture';folder.mkdir(parents=True)
            p=dict(policy(),support_mode=ch.PAIRED_REFERENCE_SUPPORT,reach_ids=['fixture'])
            reference={'version':ch.PAIRED_REFERENCE_SUPPORT,'source_ids':['reference'],
                'sources':[{'source_id':'reference','source_sha256':'f'*64,
                    'normalized_sha256':'e'*64,'terrain_binding_sha256':'a'*64}],
                'meaning':ch.REFERENCE_NOTICE}
            context=({'policy':p,'depth_source':row(),'classification_binding':binding(),
                      'reference_support':reference},row(),binding(),None,box(0,0,250,250),
                box(300,300,400,400),[{'source_id':'reference','license':'noncommercial',
                    'attribution':'Synthetic footprint producer'}])
            atomic_json(folder/'run.json',{'inputs':{'sources':[row()]}})
            atomic_json(root/'catalog/reaches.json',{'reaches':[{'id':'fixture'}]})
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            with patch.object(ch,'source_context',return_value=context), \
                 patch.object(ch,'extract',return_value=([box(0,0,50,50)],
                    {'class3_valid_depth_pixels':625,'classified_selected_area_km2':.0025})), \
                 patch('skippercast.seafloor.screen.load_snapshot',return_value=state()):
                ch.stage('fixture',root=root)
                selected,_=ch.publication_features('fixture',root=root)
                self.assertEqual(selected[0]['properties']['reference_support'],reference)
                self.assertEqual(selected[0]['properties']['source_rights'],context[-1])
                for replacement in (None,dict(reference,source_ids=['forged'])):
                    ch.stage('fixture',root=root)
                    for name in ('classified-candidates.geojson','classified-habitat.geojson'):
                        output=read_json(folder/name)
                        output['features'][0]['properties']['reference_support']=replacement
                        atomic_json(folder/name,output)
                    receipt=read_json(folder/'classified-run.json')
                    receipt['outputs']={name:sha256(folder/name) for name in receipt['outputs']}
                    atomic_json(folder/'classified-run.json',receipt)
                    with self.assertRaisesRegex(ValueError,'Unqualified classified feature'):
                        ch.publication_features('fixture',root=root)
                    # Force a fresh physical fixture for the next independent forgery.
                    (folder/'classified-run.json').unlink()

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

    def test_out_of_scope_policy_rejects_stale_publish_then_explicit_rerun_withdraws(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'var/seafloor/reaches/fixture-r01';folder.mkdir(parents=True)
            (root/'catalog').mkdir()
            p=dict(policy(),support_mode=ch.PAIRED_REFERENCE_SUPPORT,reach_ids=['fixture-r01'])
            atomic_json(root/'catalog/reaches.json',{'reaches':[{'id':'fixture-r01'}, {'id':'fixture-r02'}]})
            atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p]})
            r=row();b=binding()
            atomic_json(folder/'cells.json',{'cells':[{'id':'3310:0:0','tier':1,'source_id':'other'}]})
            atomic_json(folder/'candidates.geojson',{'features':[]})
            atomic_json(folder/'terrain.json',{'terrain':'synthetic baseline'})
            atomic_json(folder/'habitat.geojson',{'features':[]})
            atomic_json(folder/'held.geojson',{'features':[]})
            physical={'input_hash':'baseline','outputs':{n:sha256(folder/n) for n in ('cells.json','candidates.geojson')}}
            atomic_json(folder/'physical.json',physical)
            run={'physical_input_hash':'baseline','inputs':{'reach_id':'fixture-r01','sources':[r]},
                 'outputs':{n:sha256(folder/n) for n in ('cells.json','candidates.geojson','physical.json')}}
            atomic_json(folder/'run.json',run)
            original={n:(folder/n).read_bytes() for n in
                      ('run.json','physical.json','cells.json','candidates.geojson',
                       'terrain.json','habitat.geojson','held.geojson')}
            context=({'policy':p,'depth_source':r,'classification_binding':b,
                      'normalized_sha256':'d'*64},r,b,None,box(0,0,250,250),box(300,300,400,400),[])
            with patch.object(ch,'source_context',return_value=context), \
                 patch.object(ch,'extract',return_value=([box(0,0,50,50)],
                     {'class3_valid_depth_pixels':625,'classified_selected_area_km2':.0025})), \
                 patch('skippercast.seafloor.screen.load_snapshot',return_value=state()):
                first=ch.stage('fixture-r01',root=root)
                self.assertEqual(first['physical_summary']['candidate_count'],1)
                published=ch.publication_features('fixture-r01',root=root)[0]
                self.assertEqual(len(published),1)
                props=published[0]['properties']
                self.assertEqual((props['tier'],props['exportable'],props['terrain'],props['fit']),
                                 (1,False,'unknown',{'lingcod':'unknown','rockfish-reef':'unknown'}))
                self.assertEqual(props['classified_area']['new_measured_area_km2'],0)
                self.assertNotIn('terrain_grade',props);self.assertNotIn('terrain_score',props)
                p2=dict(p,reach_ids=['fixture-r02'])
                atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[p2]})
                with self.assertRaisesRegex(ValueError,'changed or withdrawn'):
                    ch.publication_features('fixture-r01',root=root)
                withdrawn=ch.stage('fixture-r01',root=root)
                self.assertEqual(withdrawn['physical_summary']['candidate_count'],0)
                self.assertEqual(ch.publication_features('fixture-r01',root=root)[0],[])
            self.assertEqual({n:(folder/n).read_bytes() for n in original},original)

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

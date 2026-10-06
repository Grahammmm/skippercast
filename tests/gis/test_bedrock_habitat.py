"""Synthetic original vector admission through the maintained publication path."""
from contextlib import ExitStack
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS, Transformer
import shapefile
from shapely.geometry import box, Polygon, mapping, shape, Point
from shapely.geometry.polygon import orient
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import bedrock_habitat as bh, classified_habitat as ch
from skippercast.seafloor.io import sha256
from skippercast.seafloor.screen import screen_candidates
from tests.gis.test_classified_habitat import state


class BedrockProductionTests(unittest.TestCase):
    def fixture(self, root, *, baseline=False):
        root=Path(root); folder=root/'var/seafloor/reaches/fixture'; folder.mkdir(parents=True)
        x,y=500000,4000000; affine=Affine(1,0,x,0,-1,y+40)
        polygon=Polygon(box(x+2,y+2,x+62,y+38).exterior.coords,
                        [box(x+26,y+16,x+34,y+24).exterior.coords])
        invalid=Polygon([(x,y),(x+10,y+10),(x,y+10),(x+10,y),(x,y)])
        streams={k:BytesIO() for k in ('shp','shx','dbf')}
        writer=shapefile.Writer(**streams,shapeType=shapefile.POLYGON)
        writer.field('MapUnitAbb','C',size=20)
        for unit,g in [('KJug?',polygon),('Jo',invalid),('Qms/Tus',box(x,y,x+64,y+40))]:
            writer.shape(mapping(orient(g,sign=-1)));writer.record(unit)
        writer.close()
        archive=root/'source.zip'
        metadata=b'synthetic original unit descriptions'
        with zipfile.ZipFile(archive,'w') as z:
            for key,stream in streams.items():z.writestr(f'Geology_SanSimeon.{key}',stream.getvalue())
            z.writestr('Geology_SanSimeon.prj',CRS.from_epsg(32610).to_wkt())
            z.writestr('Geology_SanSimeon_metadata.txt',metadata)
        source_sha=sha256(archive); cache=root/'var/seafloor/cache'/source_sha;cache.mkdir(parents=True)
        archive.rename(cache/'source.zip')
        policy={'id':'fixture-bedrock','interpretation_method':bh.METHOD,'profile':bh.PROFILE,
            'reach_ids':['fixture'],'reviewed_on':'2026-09-01','depth_source_id':'native',
            'depth_source_sha256':'a'*64,'classification_source_id':'geology',
            'classification_source_sha256':source_sha,'metadata_sha256':hashlib.sha256(metadata).hexdigest(),
            'metadata_url':'https://example.test/original','credit':'USGS synthetic',
            'notice':'Share derived products; planning only.','review_basis':'Synthetic reviewed original units.',
            'release_license':'public-domain-us-gov','vector_review':{
                'original_crs':'EPSG:32610','unit_field':'MapUnitAbb','member_stem':'Geology_SanSimeon',
                'metadata_member':'Geology_SanSimeon_metadata.txt','expected_polygon_count':3,
                'bedrock_units':['Tus','Tm','KJug','KJug?','KJf','Ksl','Jo','Jo?'],
                'excluded_units':['Qms/Tus','Qms/KJf','Qms/KJug','Qms/KJug?'],'invalid_original_records':[1],'native_windows':[[0,0,64,40]]}}
        row={'id':'native','sha256':'a'*64,'status':'usable','kind':'bathymetry','resolution_m':1.,
             'vertical_datum':'NAVD88','license':'public-domain-us-gov','url':'https://example.test/depth',
             'publisher':'Synthetic original depth'}
        source={'id':'geology','sha256':source_sha,'status':'candidate','kind':'substrate','format':'vector',
                'horizontal_crs':'EPSG:32610','license':'public-domain-us-gov',
                'url':'https://pubs.usgs.gov/sim/3327/downloads/Geology_SanSimeon.zip',
                'bytes':(cache/'source.zip').stat().st_size,'publisher':'USGS synthetic'}
        depth=root/'depth.tif'; data=np.full((40,64),30,dtype='float32')
        data[4:6,4:6]=np.nan; data[0:3,:]=100; data[37:,:]=2
        with rasterio.open(depth,'w',driver='GTiff',height=40,width=64,count=1,dtype='float32',
                           crs='EPSG:32610',transform=affine,nodata=np.nan) as ds:
            ds.write(data,1);ds.set_band_description(1,'depth_m_positive_down')
        tolocal=Transformer.from_crs(32610,3310,always_xy=True).transform
        togeo=Transformer.from_crs(32610,4326,always_xy=True).transform
        support=transform(tolocal,box(x,y,x+64,y+40))
        occupied=transform(tolocal,box(x+6,y+6,x+16,y+16)) if baseline else None
        candidates={'type':'FeatureCollection','features':[] if occupied is None else
                    [{'type':'Feature','geometry':mapping(transform(togeo,box(x+6,y+6,x+16,y+16))),
                      'properties':{'id':'graded-1'}}]}
        atomic_json(folder/'candidates.geojson',candidates)
        atomic_json(folder/'cells.json',{'cells':[{'tier':1,'source_id':'native'}]})
        from skippercast.seafloor.run import VERSION as baseline_version
        rules={'fixture':'synthetic baseline rules'}
        atomic_json(root/'catalog/habitat-rules.json',rules)
        inputs={'reach_id':'fixture','sources':[row],'rule_version':baseline_version,'habitat_rules':rules,
                'implementation':{n:sha256(Path(bh.__file__).with_name(n)) for n in bh.BASELINE_IMPLEMENTATION}}; physical={'input_hash':ch.digest(inputs),
                    'outputs':{n:sha256(folder/n) for n in ('candidates.geojson','cells.json')}}
        atomic_json(folder/'physical.json',physical)
        run={'inputs':inputs,'physical_input_hash':physical['input_hash'],
             'outputs':{n:sha256(folder/n) for n in ('candidates.geojson','cells.json','physical.json')}}
        atomic_json(folder/'run.json',run)
        native={'version':bh.BASELINE_VERSION,'crs':'EPSG:3310','features':[] if occupied is None else
                [{'type':'Feature','geometry':mapping(occupied),'properties':{'id':'graded-1'}}]}
        atomic_json(folder/'interpreted-baseline-native.geojson',native)
        atomic_json(folder/'interpreted-baseline.json',{'version':bh.BASELINE_VERSION,'reach':'fixture',
            'baseline_hashes':{n:sha256(folder/n) for n in ('run.json','physical.json','candidates.geojson')},
            'physical_input_hash':physical['input_hash'],'native_sha256':sha256(folder/'interpreted-baseline-native.geojson'),
            'reconstruction_verified':True,'review_basis':'Synthetic native reconstruction.'})
        atomic_json(root/'catalog/reaches.json',{'reaches':[{'id':'fixture'}]})
        atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[policy]})
        atomic_json(root/'deployments/production.json',{'source_use':'noncommercial','monetization':'none'})
        geo_bounds=transform(togeo,box(x-10,y-10,x+74,y+50)).bounds
        receipt={'cog_sha256':sha256(depth),'requested_bounds_wgs84':list(geo_bounds)}
        manifest={'surveys':[row,source]}
        stack=ExitStack()
        stack.enter_context(patch('skippercast.seafloor.manifest.load_manifest',return_value=manifest))
        stack.enter_context(patch.object(ch,'normalized_depth',return_value=(receipt,depth)))
        stack.enter_context(patch.object(ch,'cell_geometry',return_value=support))
        screen=state();screen['scope']=mapping(box(-179,-89,179,89))
        stack.enter_context(patch('skippercast.seafloor.screen.load_snapshot',return_value=screen))
        stack.enter_context(patch('skippercast.seafloor.screen.input_identity',return_value={'fixture':'screen'}))
        self.addCleanup(stack.close)
        return policy,row,source,depth,support,folder,manifest

    def test_integrated_stage_native_holes_edges_depth_baseline_and_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,_=self.fixture(tmp,baseline=True)
            # Every 16x16 tile is below 1000m²; one assembled patch still passes.
            staged=ch.stage('fixture',root=tmp,edge=16)
            self.assertEqual(staged['physical_summary']['candidate_count'],1)
            self.assertEqual(staged['physical_summary']['new_measured_area_km2'],0)
            native=shape(read_json(folder/'classified-native.geojson')['features'][0]['geometry'])
            self.assertGreater(native.area,1000)
            self.assertEqual(len(native.interiors),3)  # Source hole, nodata, baseline.
            self.assertTrue(ch.stage('fixture',root=tmp,edge=16)['physical_reused'])
            features,_=ch.publication_features('fixture',root=tmp)
            self.assertEqual(len(features),1)
            p=features[0]['properties']
            self.assertEqual(p['substrate']['map_unit'],'KJug?')
            self.assertTrue(p['substrate']['lithology_uncertain'])
            self.assertNotIn('normalized_code',p['substrate'])
            self.assertEqual(p['status'],'classified-area');self.assertFalse(p['exportable'])
            self.assertEqual(p['terrain'],'unknown');self.assertEqual(p['tier'],1)
            self.assertIn('exposed-bedrock',p['label']);self.assertNotIn('rugose-rock',p['label'])
            self.assertEqual(len(p['source_rights']),2)
            # Paired native spacing never becomes a terrain claim.
            self.assertEqual(staged['inputs']['physical']['sources'][0]['original_holds']['invalid_original_records'],[1])

    def test_legal_only_baseline_refresh_reuses_physics_and_rejects_stale_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(tmp)
            folder=Path(tmp)/'var/seafloor/reaches/fixture'
            current=state();current['scope']=mapping(box(-179,-89,179,89))
            def identity(snapshot):
                return {'snapshot_sha256':snapshot['snapshot_sha256']}
            with patch('skippercast.seafloor.screen.load_snapshot',return_value=current), \
                 patch('skippercast.seafloor.screen.input_identity',side_effect=identity):
                first=ch.stage('fixture',root=tmp,edge=16)
                candidate=read_json(folder/'classified-candidates.geojson')['features'][0]
                run=read_json(folder/'run.json')
                original_baseline_hash=run['physical_input_hash']
                current['snapshot_sha256']='f'*64
                current['layers'][0]['features']=[{'geometry':candidate['geometry']}]
                run['inputs']['screen']=identity(current)
                run['inputs']['screen_implementation_sha256']=sha256(Path(bh.__file__).with_name('screen.py'))
                run['last_survey']='2026-10-06T23:00:00+00:00'
                atomic_json(folder/'run.json',run)
                # The previously passing interpretation cannot borrow its old screen.
                with self.assertRaisesRegex(ValueError,'inputs changed'):
                    ch.publication_features('fixture',root=tmp)
                with patch.object(ch,'extract',side_effect=AssertionError('Legal refresh reread native physics')):
                    refreshed=ch.stage('fixture',root=tmp,edge=16)
                self.assertEqual(run['physical_input_hash'],original_baseline_hash)
                self.assertEqual(first['physical_input_hash'],refreshed['physical_input_hash'])
                self.assertTrue(refreshed['physical_reused'])
                self.assertNotEqual(first['input_hash'],refreshed['input_hash'])
                self.assertNotIn('run.json',refreshed['inputs']['physical']['sources'][0]['baseline']['baseline_hashes'])
                self.assertEqual(ch.publication_features('fixture',root=tmp)[0],[])
                self.assertEqual(len(read_json(folder/'classified-held.geojson')['features']),1)
                self.assertIn('overlap-cdfw-mpa',read_json(folder/'classified-held.geojson')['features'][0]['properties']['hold_reasons'])
                # Current physical artifacts still have to match their graded receipt.
                atomic_json(folder/'candidates.geojson',{'type':'FeatureCollection','features':[candidate]})
                for action in (ch.stage,ch.publication_features):
                    with self.assertRaisesRegex(ValueError,'baseline output hash mismatch'):
                        action('fixture',root=tmp)
                atomic_json(folder/'candidates.geojson',{'type':'FeatureCollection','features':[]})
                run['inputs']['changed_physical_input']=True
                atomic_json(folder/'run.json',run)
                for action in (ch.stage,ch.publication_features):
                    with self.assertRaisesRegex(ValueError,'baseline identity'):
                        action('fixture',root=tmp)

    def test_current_source_archive_metadata_policy_and_baseline_changes_fail_closed(self):
        for change in ('withdrawn','source-hash','archive','metadata','policy','rules','baseline'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                policy,row,source,path,support,folder,_=self.fixture(tmp)
                ch.stage('fixture',root=tmp,edge=16)
                if change=='withdrawn':source['status']='withdrawn'
                elif change=='source-hash':source['sha256']='f'*64
                elif change=='archive':
                    archive=Path(tmp)/'var/seafloor/cache'/source['sha256']/'source.zip'
                    archive.write_bytes(archive.read_bytes()+b'changed')
                elif change=='metadata':
                    policy['metadata_sha256']='f'*64
                    atomic_json(Path(tmp)/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[policy]})
                elif change=='policy':
                    atomic_json(Path(tmp)/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[]})
                elif change=='rules':
                    atomic_json(Path(tmp)/'catalog/habitat-rules.json',{'changed':True})
                else:
                    baseline=read_json(folder/'candidates.geojson');baseline['features']=[{'type':'Feature','geometry':mapping(box(-122,35,-121,36)),'properties':{'id':'changed'}}]
                    atomic_json(folder/'candidates.geojson',baseline)
                with self.assertRaises((ValueError,KeyError)):ch.publication_features('fixture',root=tmp)

    def test_rehashed_feature_forgery_cannot_change_original_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(tmp);ch.stage('fixture',root=tmp,edge=16)
            folder=Path(tmp)/'var/seafloor/reaches/fixture'
            candidates=read_json(folder/'classified-candidates.geojson')
            candidates['features'][0]['properties']['substrate']['original_record_index']=20
            atomic_json(folder/'classified-candidates.geojson',candidates)
            receipt=read_json(folder/'classified-run.json')
            receipt['outputs']['classified-candidates.geojson']=sha256(folder/'classified-candidates.geojson')
            atomic_json(folder/'classified-run.json',receipt)
            with self.assertRaisesRegex(ValueError,'production reconstruction'):
                ch.publication_features('fixture',root=tmp)

    def test_selected_support_does_not_borrow_other_source_cells_and_paired_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,manifest=self.fixture(tmp)
            other=dict(row,id='other-native',sha256='d'*64,url=row['url']+'/other')
            manifest['surveys'].append(other)
            atomic_json(folder/'cells.json',{'cells':[{'tier':1,'source_id':'other-native'}]})
            run=read_json(folder/'run.json');run['inputs']['sources'].append(other)
            physical=read_json(folder/'physical.json');physical['input_hash']=ch.digest(run['inputs'])
            physical['outputs']['cells.json']=sha256(folder/'cells.json')
            atomic_json(folder/'physical.json',physical)
            run['physical_input_hash']=physical['input_hash']
            run['outputs'].update({n:sha256(folder/n) for n in ('physical.json','cells.json')})
            atomic_json(folder/'run.json',run)
            selected=ch.stage('fixture',root=tmp,edge=16)
            self.assertEqual(selected['physical_summary']['candidate_count'],0)
            identity=selected['inputs']['physical']['sources'][0]
            self.assertEqual(identity['support_mode'],ch.SELECTED_SOURCE_SUPPORT)
            self.assertNotIn('reference_support',identity)
            self.assertEqual(ch.publication_features('fixture',root=tmp)[0],[])
            policy['support_mode']=ch.PAIRED_REFERENCE_SUPPORT
            atomic_json(Path(tmp)/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[policy]})
            paired=ch.stage('fixture',root=tmp,edge=16)
            self.assertEqual(paired['physical_summary']['candidate_count'],1)
            feature=ch.publication_features('fixture',root=tmp)[0][0]
            self.assertEqual(feature['properties']['reference_support']['source_ids'],['other-native'])
            self.assertEqual({r['source_id'] for r in feature['properties']['source_rights']},
                             {'native','other-native','geology'})
            other['status']='withdrawn'
            with self.assertRaisesRegex(ValueError,'baseline source changed'):
                ch.publication_features('fixture',root=tmp)

    def test_reviewed_windows_reject_overlap_outside_extent_and_source_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,_=self.fixture(tmp)
            policy['vector_review']['native_windows']=[[0,0,32,40],[16,0,32,40]]
            with self.assertRaisesRegex(ValueError,'overlap'):bh.validate_policy(policy)
            policy['vector_review']['native_windows']=[[64,0,1,1]]
            binding={'row':source,'policy':policy,'archive':Path(tmp)/'var/seafloor/cache'/source['sha256']/'source.zip',
                     'reviewed_depth_bounds_wgs84':[-130,30,-120,40]}
            with self.assertRaisesRegex(ValueError,'extent'):
                bh.extract(row,binding,path,support,unary_union([]),root=tmp)
            policy['vector_review']['native_windows']=[[0,0,64,40]]
            binding['reviewed_depth_bounds_wgs84']=[-122,35,-121,36]
            with self.assertRaisesRegex(ValueError,'source bounds'):
                bh.extract(row,binding,path,support,unary_union([]),root=tmp)

    def test_stable_geometry_ids_do_not_depend_on_component_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,_=self.fixture(tmp)
            original=bh.Patch('2','Jo',box(0,0,50,50),2500,'EPSG:3310')
            extra=bh.Patch('3','Tm',box(100,100,150,150),2500,'EPSG:3310')
            binding={'row':source}
            first=bh.features_for([original,extra],'fixture',policy,row,binding)['features']
            reordered=bh.features_for([extra,original],'fixture',policy,row,binding)['features']
            self.assertEqual(first[0]['properties']['id'],reordered[1]['properties']['id'])
            self.assertEqual(first[1]['properties']['id'],reordered[0]['properties']['id'])

    def test_depth_description_missing_and_pixel_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,_=self.fixture(tmp)
            binding={'row':source,'policy':policy,'archive':Path(tmp)/'var/seafloor/cache'/source['sha256']/'source.zip',
                     'reviewed_depth_bounds_wgs84':[-130,30,-120,40]}
            with self.assertRaisesRegex(ValueError,'pixel budget'):
                bh.extract(row,binding,path,support,unary_union([]),root=tmp,max_pixels=1)
            with rasterio.open(path,'r+') as ds:ds.set_band_description(1,'unreviewed-depth')
            with self.assertRaisesRegex(ValueError,'positive-down'):
                bh.extract(row,binding,path,support,unary_union([]),root=tmp)

    def test_whole_polygon_exclusion_and_contract_no_spoofed_rugosity(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(tmp);ch.stage('fixture',root=tmp,edge=16)
            candidates=read_json(Path(tmp)/'var/seafloor/reaches/fixture/classified-candidates.geojson')
            f=candidates['features'][0];p=f['properties'];self.assertIsNotNone(ch.assessment(p))
            native=read_json(Path(tmp)/'var/seafloor/reaches/fixture/classified-native.geojson')['features'][0]['geometry']
            exclusion={'type':'Feature','geometry':f['geometry'],'properties':{}}
            passing,held,_=screen_candidates(candidates,state(exclusion),native_geometries={p['id']:native})
            self.assertEqual(len(passing['features']),0);self.assertEqual(len(held['features']),1)
            p['substrate']['normalized_code']=3
            self.assertIsNone(ch.assessment(p))

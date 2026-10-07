"""Offline original Monterey source contract and integrated private holds."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import hashlib,tempfile,unittest,zipfile
from unittest.mock import patch
import numpy as np,rasterio,shapefile
from pyproj import CRS,Transformer
from shapely.geometry import box,Polygon,mapping,shape
from shapely.geometry.polygon import orient
from shapely.ops import transform
from skippercast.platform.contracts import atomic_json,read_json
from skippercast.seafloor import bedrock_habitat as bh,classified_habitat as ch
from skippercast.seafloor.io import sha256
from tests.gis import test_bedrock_habitat as fixtures


class MontereyTests(unittest.TestCase):
    def fixture(self,tmp,*,bad_code=False,bad_source=False):
        policy,row,source,path,old_support,folder,manifest=fixtures.BedrockProductionTests.fixture(self,tmp)
        root=Path(tmp);x,y=500000,4000000
        streams={k:BytesIO() for k in ('shp','shx','dbf')};writer=shapefile.Writer(**streams,shapeType=shapefile.POLYGON)
        writer.field('PTYPE','C',size=50);writer.field('Area','F',size=19,decimal=11)
        pure=set([i for i in range(894) if i not in (318,676)][:456])
        bow=Polygon([(x,y),(x+10,y+10),(x,y+10),(x+10,y),(x,y)])
        for i in range(894):
            unit='Kgr' if i in pure else 'Qms'
            g=box(x+100,y,x+101,y+1)
            if i==0:g=Polygon(box(x+2,y-22,x+30,y+38).exterior.coords,[box(x+8,y,x+12,y+4).exterior.coords])
            if i==1:unit='Kgrcw';g=box(x+34,y-22,x+62,y+38)
            if i==318:unit='Qmsd';g=bow
            if i==676:g=bow
            if bad_source and i==0:g=bow
            if bad_code and i==893:unit='Kgcw' # Never alias metadata typo to actual code.
            writer.shape(mapping(orient(g,sign=-1)));writer.record(unit,g.area)
        writer.close();metadata=b'<metadata>Synthetic original Monterey</metadata>'
        archive=root/'monterey.zip';contract=bh.SOURCE_CONTRACTS[bh.MONTEREY]
        with zipfile.ZipFile(archive,'w') as z:
            for k,v in streams.items():z.writestr(contract['member_stem']+'.'+k,v.getvalue())
            z.writestr(contract['member_stem']+'.prj',CRS.from_epsg(32610).to_wkt())
            z.writestr(contract['metadata_member'],metadata)
        digest=sha256(archive);cache=root/'var/seafloor/cache'/digest;cache.mkdir();archive.rename(cache/'source.zip')
        source.update(sha256=digest,bytes=(cache/'source.zip').stat().st_size)
        policy.update(classification_source_sha256=digest,metadata_sha256=hashlib.sha256(metadata).hexdigest())
        policy['vector_review']=dict(deepcopy(contract),source_profile=bh.MONTEREY,original_crs='EPSG:32610',expected_polygon_count=894,invalid_original_records=[],native_windows=[[0,0,64,64]])
        atomic_json(root/ch.POLICY_FILE,{'schema_version':1,'profile':ch.PROFILE,'sources':[policy]})
        with rasterio.open(path) as ds:profile=ds.profile
        profile['height']=64;data=np.full((64,64),30,dtype='float32');data[4:6,4:6]=np.nan;data[:3,:]=100;data[-3:,:]=2
        with rasterio.open(path,'w',**profile) as ds:ds.write(data,1);ds.set_band_description(1,'depth_m_positive_down')
        tolocal=Transformer.from_crs(32610,3310,always_xy=True).transform;togeo=Transformer.from_crs(32610,4326,always_xy=True).transform
        support=transform(tolocal,box(x,y-24,x+64,y+40))
        receipt,_=ch.normalized_depth(row,tmp);receipt.update(cog_sha256=sha256(path),requested_bounds_wgs84=list(transform(togeo,box(x-10,y-34,x+74,y+50)).bounds))
        mock=patch.object(ch,'cell_geometry',return_value=support);mock.start();self.addCleanup(mock.stop)
        return policy,row,source,path,support,folder,cache/'source.zip'

    def test_nested_xml_reader_full_domain_and_bad_header_hash_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,_,_,_,_,_,archive=self.fixture(tmp)
            bh.validate_policy(policy);records,units,holds=bh.original_vectors(archive,policy,32610)
            self.assertEqual(len(records),456);self.assertEqual(units['1'],'Kgrcw');self.assertEqual(holds['invalid_original_records'],[])
            for key,value in [('unit_field','MapUnitAbb'),('member_stem','arbitrary'),('expected_polygon_count',893),('source_profile','unapproved')]:
                changed=deepcopy(policy);changed['vector_review'][key]=value
                with self.subTest(key=key),self.assertRaises(ValueError):bh.original_vectors(archive,changed,32610)
            changed=deepcopy(policy);changed['metadata_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'metadata changed'):bh.original_vectors(archive,changed,32610)
        with tempfile.TemporaryDirectory() as tmp:
            policy,_,_,_,_,_,archive=self.fixture(tmp,bad_code=True)
            with self.assertRaisesRegex(ValueError,'map-unit code'):bh.original_vectors(archive,policy,32610)

    def test_invalid_original_source_never_enters_quarantine_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,_,_,_,_,_,archive=self.fixture(tmp,bad_source=True)
            with self.assertRaisesRegex(ValueError,'invalid-record holds'):
                bh.original_vectors(archive,policy,32610)

    def test_integrated_stage_cache_publication_and_private_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,archive=self.fixture(tmp)
            original=bh.strict_geographic
            def reject_right(g):
                local=transform(Transformer.from_crs(3310,32610,always_xy=True).transform,g)
                if local.centroid.x>500032:raise ValueError('Synthetic invalid derived projection')
                return original(g)
            with patch.object(bh,'strict_geographic',side_effect=reject_right):
                staged=ch.stage('fixture',root=tmp,edge=16)
                self.assertEqual(staged['physical_summary']['candidate_count'],1)
                self.assertEqual(staged['physical_summary']['bedrock_projection_held_count'],1)
                audit=read_json(folder/ch.BEDROCK_AUDIT_FILE)
                self.assertEqual(len(audit['quarantine']),1);self.assertFalse(audit['quarantine'][0]['geometry_repaired'])
                self.assertTrue(shape(audit['quarantine'][0]['geometry']).is_valid)
                self.assertIn(ch.BEDROCK_AUDIT_FILE,staged['outputs'])
                self.assertIn('bedrock_projection',staged['inputs']['physical'])
                self.assertEqual(staged['inputs']['physical']['bedrock_quarantine']['component_count'],1)
                cached=ch.stage('fixture',root=tmp,edge=16);self.assertTrue(cached['physical_reused'])
                features,_=ch.publication_features('fixture',root=tmp)
                self.assertEqual(len(features),1);p=features[0]['properties']
                self.assertEqual(p['classified_area']['source_profile'],bh.MONTEREY)
                self.assertEqual(p['substrate']['map_unit'],'Kgr');self.assertNotIn('normalized_code',p['substrate'])
                self.assertFalse(p['exportable']);self.assertEqual(p['terrain'],'unknown')
                self.assertNotIn('quarantine',str(features))
                # Changing a hash-bound private native hold cannot borrow a cached pass.
                atomic_json(folder/ch.BEDROCK_AUDIT_FILE,dict(audit,quarantine=[]))
                with self.assertRaisesRegex(ValueError,'private artifact'):ch.publication_features('fixture',root=tmp)

    def test_missing_depth_and_300ft_limit_are_native_and_tiny_stays_tiny(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,archive=self.fixture(tmp)
            with rasterio.open(path,'r+') as ds:
                data=ds.read(1);data[:]=np.nan;ds.write(data,1)
            self.assertEqual(ch.stage('fixture',root=tmp,edge=16)['physical_summary']['candidate_count'],0)
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,archive=self.fixture(tmp)
            with rasterio.open(path,'r+') as ds:
                data=ds.read(1);data[:]=91.441;ds.write(data,1)
            self.assertEqual(ch.stage('fixture',root=tmp,edge=16)['physical_summary']['candidate_count'],0)

    def test_conservative_baseline_encloses_projection_only_never_repairs_source(self):
        original=box(0,0,10,10);invalid=Polygon([(0,0),(10,10),(0,10),(10,0),(0,0)])
        with patch.object(bh,'transform',return_value=invalid):
            native,audit=bh.native_baseline([{'id':'prior','crs':3310,'geometry':original}],32610)
        used=native.by_record['prior'];self.assertEqual(used.bounds,invalid.bounds)
        self.assertTrue(all(used.covers(shape({'type':'Point','coordinates':p})) for p in invalid.exterior.coords))
        self.assertTrue(audit['components'][0]['conservative_envelope'])
        self.assertEqual(audit['component_count'],1)
        with self.assertRaisesRegex(ValueError,'Invalid classified'):
            bh.native_baseline([{'id':'bad-original','crs':3310,'geometry':invalid}],32610)
        unknown=deepcopy(bh.SOURCE_CONTRACTS[bh.MONTEREY]);unknown['bedrock_units'].append('arbitrary')
        with tempfile.TemporaryDirectory() as tmp:
            policy,*_=self.fixture(tmp);policy['vector_review'].update(unknown)
            with self.assertRaises(ValueError):bh.validate_policy(policy)

    def test_legal_only_refresh_keeps_monterey_physics(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(tmp);first=ch.stage('fixture',root=tmp,edge=16)
            folder=Path(tmp)/'var/seafloor/reaches/fixture';run=read_json(folder/'run.json')
            run['inputs']['screen']={'changed':True};run['last_survey']='2026-10-06';atomic_json(folder/'run.json',run)
            with patch.object(ch,'extract',side_effect=AssertionError('Must reuse physical candidate cache')):
                second=ch.stage('fixture',root=tmp,edge=16)
            self.assertTrue(second['physical_reused']);self.assertEqual(first['physical_input_hash'],second['physical_input_hash'])

    def test_stale_legal_pass_rejected_then_cached_physics_rescreened(self):
        from tests.gis.test_classified_habitat import state
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(tmp);current=state();current['scope']=mapping(box(-179,-89,179,89))
            identity=lambda snapshot:{'snapshot_sha256':snapshot['snapshot_sha256']}
            with patch('skippercast.seafloor.screen.load_snapshot',return_value=current),patch('skippercast.seafloor.screen.input_identity',side_effect=identity):
                first=ch.stage('fixture',root=tmp,edge=16)
                folder=Path(tmp)/'var/seafloor/reaches/fixture';candidate=read_json(folder/'classified-candidates.geojson')['features'][0]
                current['snapshot_sha256']='f'*64;current['layers'][0]['features']=[{'geometry':candidate['geometry']}]
                with self.assertRaisesRegex(ValueError,'inputs changed'):ch.publication_features('fixture',root=tmp)
                with patch.object(ch,'extract',side_effect=AssertionError('Must reuse physical cache')):
                    refreshed=ch.stage('fixture',root=tmp,edge=16)
                self.assertTrue(refreshed['physical_reused']);self.assertEqual(first['physical_input_hash'],refreshed['physical_input_hash'])
                self.assertNotEqual(first['input_hash'],refreshed['input_hash'])
                features,_=ch.publication_features('fixture',root=tmp)
                self.assertLess(len(features),first['summary']['classified_area_count'])
                # Native positive units cannot pretend to be legacy rugose or ranked terrain.
                p=deepcopy(candidate['properties']);p['substrate']['normalized_code']=3
                self.assertIsNone(ch.assessment(p))
                p=deepcopy(candidate['properties']);p['terrain']={'grade':'A'}
                self.assertIsNone(ch.assessment(p))

    def test_projected_prior_overlap_quarantines_whole_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,archive=self.fixture(tmp)
            records,_,_=bh.original_vectors(archive,policy,32610)
            _,_,binding,_,_,existing,_=bh.source_context(tmp,'fixture',policy)
            prior=transform(Transformer.from_crs(32610,3310,always_xy=True).transform,box(500004,3999990,500006,4000010))
            binding['prior_components']=[{'id':'prior-native','crs':3310,'geometry':prior}]
            # Model native-to-publication crossing after assembly, while keeping source polygons unchanged.
            with patch.object(bh.kernel,'assemble_components',return_value=[('0',records['0']),('1',records['1'])]):
                patches,summary=bh.extract(row,binding,path,support,existing,root=tmp,edge=16)
            self.assertEqual([p.record for p in patches],['1'])
            self.assertEqual(summary['bedrock_projection_overlap_count'],1)
            held=summary['_private_quarantine'][0]
            self.assertEqual(held['hold_category'],'representation-prior-overlap')
            self.assertTrue(shape(held['geometry']).equals_exact(records['0'],0))
            self.assertEqual(held['source_sha256'],policy['classification_source_sha256'])
            self.assertFalse(held['geometry_repaired'])

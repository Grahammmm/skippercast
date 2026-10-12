"""Explicit SanSimeon private auditing leaves omitted profile semantics unchanged."""
from copy import deepcopy
import tempfile,unittest,zipfile,hashlib,shapefile
from io import BytesIO
from pathlib import Path
from pyproj import CRS
from skippercast.seafloor.io import sha256
from unittest.mock import patch
from shapely.geometry import box
from skippercast.seafloor import bedrock_habitat as bh,classified_habitat as ch
from tests.gis import test_bedrock_habitat as fixtures

class AuditedSanSimeonTests(unittest.TestCase):
    def test_explicit_bounded_contract_and_legacy_omission(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,row,source,path,support,folder,manifest=fixtures.BedrockProductionTests.fixture(self,tmp)
            self.assertFalse(bh.audited(policy))
            explicit=deepcopy(policy);explicit['vector_review'].update(source_profile=bh.SAN_SIMEON_AUDITED,expected_polygon_count=625,invalid_original_records=[123])
            self.assertTrue(bh.audited(explicit));bh.validate_policy(explicit)
            for key,value in [('expected_polygon_count',624),('invalid_original_records',[]),('member_stem','arbitrary'),('bedrock_units',['Tus'])]:
                bad=deepcopy(explicit);bad['vector_review'][key]=value
                with self.subTest(key=key),self.assertRaises(ValueError):bh.validate_policy(bad)
            g=box(1,1,41,41);patches=[bh.Patch('0','Tus',g,g.area,'EPSG:26910')]
            with patch.object(bh,'geographic',return_value=g),patch.object(bh,'strict_geographic',return_value=g):
                legacy=bh.features_for(patches,'fixture',policy,row,{'row':source})
                newer=bh.features_for(patches,'fixture',explicit,row,{'row':source})
                self.assertNotIn('source_profile',legacy['features'][0]['properties']['classified_area'])
                props=newer['features'][0]['properties'];self.assertEqual(props['classified_area'].pop('source_profile'),bh.SAN_SIMEON_AUDITED)
                self.assertEqual(legacy,newer)
                props['classified_area']['source_profile']=bh.SAN_SIMEON_AUDITED
                self.assertIsNotNone(bh.assessment(props));self.assertFalse(props['exportable'])
                self.assertNotIn('normalized_code',props['substrate']);self.assertEqual(props['terrain'],'unknown')

    def test_original_sansimeon_polygonz_header_and_invalid_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,_,_,_,_,_,_=fixtures.BedrockProductionTests.fixture(self,tmp)
            streams={s:BytesIO() for s in ('shp','shx','dbf')}
            w=shapefile.Writer(**streams,shapeType=shapefile.POLYGONZ);w.field('MapUnitAbb','C',size=16)
            for i in range(625):
                coords=[(500000,4000000,0),(500020,4000000,0),(500020,4000020,0),(500000,4000020,0),(500000,4000000,0)]
                if i==123:coords=[(500000,4000000,0),(500020,4000020,0),(500000,4000020,0),(500020,4000000,0),(500000,4000000,0)]
                w.polyz([coords]);w.record('Tus' if i<329 else 'Qms')
            w.close();archive=Path(tmp)/'original-z.zip';meta=b'Synthetic SanSimeon original PolygonZ'
            with zipfile.ZipFile(archive,'w') as z:
                for suffix,stream in streams.items():z.writestr('Geology_SanSimeon.'+suffix,stream.getvalue())
                z.writestr('Geology_SanSimeon.prj',CRS.from_epsg(32610).to_wkt());z.writestr('Geology_SanSimeon_metadata.txt',meta)
            policy.update(classification_source_sha256=sha256(archive),metadata_sha256=hashlib.sha256(meta).hexdigest())
            policy['vector_review'].update(expected_polygon_count=625,invalid_original_records=[123])
            records,units,holds=bh.original_vectors(archive,policy,32610)
            self.assertEqual(len(records),328);self.assertEqual(holds['invalid_original_records'],[123])
            policy['vector_review']['source_profile']=bh.SAN_SIMEON_AUDITED
            audited,_,holds=bh.original_vectors(archive,policy,32610)
            self.assertEqual(set(records),set(audited));self.assertTrue(all(records[k].equals_exact(audited[k],0) for k in records))
            self.assertEqual(holds['pure_bedrock_record_count'],329)

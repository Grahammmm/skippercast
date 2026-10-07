"""Original SanSimeon PolygonZ remains accepted; Monterey requires Polygon."""
import tempfile,unittest,zipfile,hashlib,shapefile,struct
from io import BytesIO
from pathlib import Path
from pyproj import CRS
from skippercast.seafloor import bedrock_habitat as bh
from skippercast.seafloor.io import sha256
from tests.gis import test_bedrock_habitat as fixtures
from tests.gis import test_monterey_bedrock as monterey

class BedrockHeaderTests(unittest.TestCase):
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

    def test_monterey_polygonz_header_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy,_,_,_,_,_,archive=monterey.MontereyTests.fixture(self,tmp)
            with zipfile.ZipFile(archive) as z:members={n:z.read(n) for n in z.namelist()}
            member=policy['vector_review']['member_stem']+'.shp'
            data=bytearray(members[member]);struct.pack_into('<i',data,32,shapefile.POLYGONZ);members[member]=data
            with zipfile.ZipFile(archive,'w') as z:
                for n,data in members.items():z.writestr(n,data)
            policy['classification_source_sha256']=sha256(archive)
            with self.assertRaisesRegex(ValueError,'shape/attribute header'):
                bh.original_vectors(archive,policy,32610)

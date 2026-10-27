"""C1 manifest integration on tiny offline GeoTIFFs, never a real-source run."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

from research.scripts.coast_mvp import coast_qa as qa
from tests._support import ROOT

FIXTURE = ROOT / 'research/tests/fixtures/coast_mvp/qa'


class C1AdapterTest(unittest.TestCase):
    def build(self, directory):
        d = Path(directory)
        sources = []
        for ident in ('a','b','mosaic'):
            rows, _ = qa.ascii_grid(FIXTURE/f'{ident}.asc')
            data = np.array([[v if v is not None else -9999 for v in row] for row in rows], dtype='float32')
            # B native positive-down + a constant elevation offset of +2 m.
            if ident == 'b':
                data = np.where(data != -9999, -data+2, -9999)
            p = d/f'{ident}.tif'
            with rasterio.open(p,'w',driver='GTiff',width=4,height=4,count=1,dtype='float32',
                               crs='EPSG:3310',transform=from_origin(0,40,10,10),nodata=-9999) as grid:
                grid.write(data,1)
            if ident != 'mosaic':
                sources.append(dict(id=ident,path=p.name,sha256=qa.digest(p),
                                    value_convention='depth_positive_down' if ident == 'b' else 'elevation_positive_up',
                                    vertical_offset_m=2 if ident == 'b' else 0))
        manifest = dict(schema_version=1,units='m',value_convention='elevation_positive_up',
                        outputs=dict(elevation=dict(path='mosaic.tif',sha256=qa.digest(d/'mosaic.tif'))),sources=sources)
        p = d/'manifest.json'
        p.write_text(json.dumps(manifest))
        config = d/'region.json'
        config.write_text(json.dumps(dict(region='synthetic-central',segments=[dict(id='fixture',manifest=p.name)])))
        return p, config

    def test_c1_manifest_geoTIFF_overlap_sign_offset_and_hole(self):
        with tempfile.TemporaryDirectory() as d:
            _, config = self.build(d)
            report = qa.packet(config,Path(d)/'packet')
            s = report['segments'][0]
            self.assertEqual(s['stats']['valid_cells'],15)
            self.assertEqual(s['hole_count'],1)
            self.assertEqual(s['seam_rms'][0]['overlap_cells'],3)
            self.assertEqual(s['seam_rms'][0]['rms_m'],3)
            self.assertEqual(s['seam_rms'][0]['mean_delta_m'],3)

    def test_c1_hash_mismatch_refuses_before_packet(self):
        for target in ('mosaic.tif','a.tif'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as d:
                _, config = self.build(d)
                with (Path(d)/target).open('ab') as f:
                    f.write(b'changed')
                with self.assertRaisesRegex(ValueError,'hash mismatch'):
                    qa.packet(config,Path(d)/'packet')
                self.assertFalse((Path(d)/'packet').exists())

    def test_c1_missing_overlap_is_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            manifest, config = self.build(d)
            p = Path(d)/'b.tif'
            with rasterio.open(p,'r+') as grid:
                data = grid.read(1)
                data[:, :2] = -9999
                grid.write(data,1)
            doc = json.loads(manifest.read_text())
            doc['sources'][1]['sha256'] = qa.digest(p)
            manifest.write_text(json.dumps(doc))
            seam = qa.packet(config,Path(d)/'packet')['segments'][0]['seam_rms'][0]
            self.assertIsNone(seam['rms_m'])
            self.assertEqual(seam['status'],'unavailable')

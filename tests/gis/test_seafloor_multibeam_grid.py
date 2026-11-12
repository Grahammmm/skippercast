"""Private derived grids keep provenance, masks, sampling semantics and gates."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer

from skippercast.seafloor.adapters.multibeam_grid import DESCRIPTIONS, VERSION
from skippercast.seafloor.source_ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import qualify_row, validate_manifest
from skippercast.seafloor.normalized import verify_review
from skippercast.seafloor.coverage import footprint
from skippercast.seafloor.run import run
from tests._support import ROOT


class PrivateGridTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root/'catalog').mkdir()
        shutil.copyfile(ROOT/'catalog/survey.schema.json',self.root/'catalog/survey.schema.json')
        self.source = self.root/'fixture.tif'
        yy,xx = np.indices((160,160)); depth=(50-8*np.exp(-((xx-80)**2+(yy-80)**2)/150)).astype('float32')
        data=np.array([depth,np.full_like(depth,6),np.full_like(depth,.5),depth-1,depth+1])
        data[:,20:25,20:25]=np.nan  # Native missing measurements.
        data[1,30:35,30:35]=2  # Sparse source bins must be excluded.
        data[3,40:45,40:45]=90; data[4,40:45,40:45]=92; data[0,40:45,40:45]=91
        with rasterio.open(self.source,'w',driver='GTiff',width=160,height=160,count=5,
                dtype='float32',crs=3310,transform=from_origin(-275,525,5,5),nodata=np.nan) as ds:
            ds.write(data)
            for i,name in enumerate(DESCRIPTIONS,1):ds.set_band_description(i,name)
            ds.update_tags(interpolation='none',depth_basis='nominal',vertical_datum='unknown')
        prep={'scope':'private-multibeam-grid-parity','output_sha256':sha256(self.source),
              'derived_bin_spacing_m':5,'vertical_datum':'unknown','native_resolution':'irregular soundings',
              'uncertainty':'unknown','count_support_mismatches':0,'source_qualified':False,'fishing_target':False,
              'exportable':False,'new_measured_km2':0,'new_physical_candidates':0,'new_public_locations':0,
              'originals':{'original.mb57':'a'*64},'beam_table_sha256':['b'*64],
              'grid_sha256':['c'*64,'d'*64,'e'*64],'grid_receipt_sha256':'f'*64,'horizontal_crs':'EPSG:3310'}
        self.sidecar=self.source.with_suffix('.json');self.sidecar.write_text(json.dumps(prep))
        self.row=deepcopy(next(r for r in json.loads((ROOT/'catalog/surveys.json').read_text())['surveys'] if r['status']=='usable'))
        for k in ('adapter_review','rights_review','resolution_profile','terrain_support','habitat_quality_hold'):self.row.pop(k,None)
        self.row.update(id='fixture-grid',publisher='Original sonar contributor',url='https://www.marine-geo.org/fixture',
                        landing_page='https://www.marine-geo.org/fixture',format='measured-multibeam-grid',kind='bathymetry',
                        status='candidate',license='unknown',derived_from=[],resolution_m=5,vertical_datum='unknown',
                        archive_member='unknown',sha256=sha256(self.source),bytes=self.source.stat().st_size)
        self.row['grid_preparation']={'profile':VERSION,'preparation_receipt_sha256':sha256(self.sidecar),
            'preparation_code_sha256':'1'*64,'native_sampling':'irregular-original-soundings',
            'grid_spacing_m':5,'minimum_good_soundings':3}
        t=Transformer.from_crs(3310,4326,always_xy=True)
        self.bounds=[*t.transform(-275,-275),*t.transform(525,525)]

    def test_sign_sparse_missing_mixed_depth_and_unknown_uncertainty(self):
        receipt,downloaded,reused=ingest(self.row,self.bounds,root=self.root,local=self.source)
        self.assertFalse(downloaded or reused);self.assertEqual(receipt['native_resolution_m'],'unknown')
        self.assertEqual(receipt['grid_spacing_m'],[5,5]);self.assertEqual(receipt['uncertainty_type'],'unknown')
        folder=self.root/'var/seafloor/cache'/self.row['sha256']
        output=next(p.with_suffix('.tif') for p in folder.glob('*.json') if json.loads(p.read_text()).get('cog_sha256')==receipt['cog_sha256'])
        with rasterio.open(output) as ds:
            self.assertEqual(ds.count,5);self.assertEqual(ds.descriptions,DESCRIPTIONS)
            self.assertGreater(ds.read(1)[80,80],0);self.assertEqual(ds.read(2)[80,80],6)
            for y,x in ((22,22),(32,32),(42,42)):self.assertEqual(ds.dataset_mask()[y,x],0)
            self.assertEqual(ds.transform,from_origin(-275,525,5,5))
        self.assertEqual(ingest(self.row,self.bounds,root=self.root), (receipt,False,True))
        row=qualify_row(self.row,receipt,rights_url=self.row['url'],physical_only=True)
        validate_manifest({'surveys':[row]},self.root);verify_review(receipt,row['adapter_review'],output)
        self.assertAlmostEqual(footprint(output,self.bounds).area,(160*160-75)*25,delta=25)
        with self.assertRaisesRegex(ValueError,'private-only'):
            qualify_row(self.row,receipt,rights_url=self.row['url'])
        for change in ({'status':'usable'},{'license':'public-domain-us-gov'}):
            bad=deepcopy(row);bad.update(change)
            with self.assertRaises(Exception):validate_manifest({'surveys':[bad]},self.root)

    def test_binding_review_and_numeric_spelling_keep_one_identity(self):
        receipt,_,_=ingest(self.row,self.bounds,root=self.root,local=self.source)
        numeric=deepcopy(self.row);numeric['resolution_m']=5.0;numeric['grid_preparation']['grid_spacing_m']=5.0
        self.assertEqual(ingest(numeric,self.bounds,root=self.root),(receipt,False,True))
        row=qualify_row(self.row,receipt,rights_url=self.row['url'],physical_only=True)
        for field,value in (('grid_spacing_m',[5,6]),('native_sampling','different'),
                            ('preparation_receipt_sha256','2'*64)):
            bad=deepcopy(row);bad['adapter_review'][field]=value
            with self.subTest(field=field),self.assertRaises(Exception):
                validate_manifest({'surveys':[bad]},self.root)
        with self.assertRaisesRegex(ValueError,'does not intersect'):
            ingest(self.row,[-125,32,-124,33],root=self.root)

    def test_float32_nominal_limit_sparse_and_deep_neighbors(self):
        from skippercast.seafloor.adapters.multibeam_grid import supported_window
        with rasterio.open(self.source,'r+') as ds:
            a=ds.read()
            for x,depth,count in ((80,91.44,3),(81,91.45,3),(82,0,3),(83,50,2)):
                a[:,80,x]=[depth,count,.5,depth,depth]
            ds.write(a)
        with rasterio.open(self.source) as ds:
            from rasterio.windows import Window
            values,valid=supported_window(ds,Window(80,80,4,1))
        self.assertEqual(valid.tolist(),[[True,True,False,False]])
        shallow=valid&(values[4]<=np.float32(91.44))
        self.assertEqual(shallow.tolist(),[[True,False,False,False]])

    def test_shared_normalization_dependencies_invalidate_private_cache(self):
        receipt,_,_=ingest(self.row,self.bounds,root=self.root,local=self.source)
        original_hash=sha256
        for name in ('raster.py','normalized.py'):
            def changed(path):
                return '3'*64 if Path(path).name==name else original_hash(path)
            with self.subTest(dependency=name),patch('skippercast.seafloor.adapters.multibeam_grid.sha256',side_effect=changed):
                updated,_,reused=ingest(self.row,self.bounds,root=self.root)
                self.assertFalse(reused)
                self.assertNotEqual(updated['inputs'],receipt['inputs'])
                self.assertEqual(updated['raster_identity'],receipt['raster_identity'])

    def test_changed_source_receipt_and_wrong_diagnostic_band_fail(self):
        for kind in ('bytes','receipt','band','count','negative-dispersion'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as out:
                row=deepcopy(self.row); source=Path(out)/'changed.tif';shutil.copyfile(self.source,source)
                sidecar=source.with_suffix('.json');shutil.copyfile(self.sidecar,sidecar)
                if kind=='bytes':source.write_bytes(b'changed')
                elif kind=='receipt':sidecar.write_text('{}')
                else:
                    with rasterio.open(source,'r+') as ds:
                        if kind=='band':ds.set_band_description(2,'producer_uncertainty_m')
                        else:
                            band=2 if kind=='count' else 3;a=ds.read(band);a[80,80]=1.5 if kind=='count' else -1;ds.write(a,band)
                    row['sha256']=sha256(source);row['bytes']=source.stat().st_size
                    prep=json.loads(sidecar.read_text());prep['output_sha256']=row['sha256'];sidecar.write_text(json.dumps(prep))
                    row['grid_preparation']['preparation_receipt_sha256']=sha256(sidecar)
                with self.assertRaises(ValueError):ingest(row,self.bounds,root=Path(out)/'isolated',local=source)

    def test_private_source_never_fetches_or_enters_default_run(self):
        with patch('skippercast.seafloor.fetch.fetch_source',side_effect=AssertionError('No landing-page download')):
            with self.assertRaises(FileNotFoundError):ingest(self.row,self.bounds,root=self.root,fetch=True)
        receipt,_,_=ingest(self.row,self.bounds,root=self.root,local=self.source)
        row=qualify_row(self.row,receipt,rights_url=self.row['url'],physical_only=True)
        (self.root/'catalog/surveys.json').write_text(json.dumps({'surveys':[row]}))
        rules=json.loads((ROOT/'catalog/habitat-rules.json').read_text());rules['substrate_bindings']=[]
        (self.root/'catalog/habitat-rules.json').write_text(json.dumps(rules))
        (self.root/'requirements-survey.txt').write_text('fixture')
        ref=self.root/'var/seafloor/reference';ref.mkdir(parents=True)
        (self.root/'dist/data').mkdir(parents=True)
        (self.root/'dist/data/atlas.json').write_text('{"points":[],"zones":[],"drift_corridors":[]}')
        (self.root/'dist/data/seafloor-ledger.json').write_text('{"reaches":[],"totals":{}}')
        (self.root/'catalog/reaches.json').write_text('{"input_hash":"grid","reaches":[{"id":"fixture-r01"}]}')
        (ref/'cells.json').write_text(json.dumps({'input_hash':'grid','cells':[{'id':'3310:0:0','reach':'fixture-r01',
            'tier':0,'band_area_m2':50000,'reference_unknown_area_m2':0}]}))
        (ref/'run.json').write_text(json.dumps({'input_hash':'grid','output_hashes':{'cells.json':sha256(ref/'cells.json')}}))
        ledger=(self.root/'dist/data/seafloor-ledger.json').read_bytes()
        result,unchanged=run('fixture-r01',root=self.root,physical_only=True)
        self.assertFalse(unchanged);self.assertGreater(result['ledger_summary']['selected_valid_km2'],0)
        self.assertGreater(result['ledger_summary']['physical_candidate_count'],0)
        self.assertEqual((self.root/'dist/data/seafloor-ledger.json').read_bytes(),ledger)
        self.assertTrue((self.root/'var/seafloor/private-reaches/fixture-r01/run.json').exists())
        with patch('skippercast.seafloor.run.footprint') as processing:
            same,unchanged=run('fixture-r01',root=self.root,physical_only=True)
            self.assertTrue(unchanged);self.assertEqual(same,result);processing.assert_not_called()
        from skippercast.seafloor.manifest import physical_source
        self.assertFalse(physical_source(row));self.assertTrue(physical_source(row,physical_only=True))
        candidates=json.loads((self.root/'var/seafloor/private-reaches/fixture-r01/candidates.geojson').read_text())
        self.assertTrue(all(not f['properties'].get('exportable',False) for f in candidates['features']))
        for feature in candidates['features']:
            self.assertTrue(all(value in (1,2,3) for value in feature['properties']['fit'].values()))
            self.assertIn('derived-multibeam-source-review',feature['properties']['hold_reasons'])
            self.assertEqual(feature['properties']['measured_support']['native_resolution_m'],'unknown')
            self.assertEqual(feature['properties']['measured_support']['full_bin_insonification'],'unverified')

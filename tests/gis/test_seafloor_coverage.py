"""Coverage and terrain fixtures distinguish source data from survey envelopes."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from pyproj import Transformer

from skippercast.seafloor.coverage import classify_cells, valid_depth, footprint, priority
from skippercast.seafloor.terrain import derivatives
from skippercast.seafloor.ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import qualify_row, promote_draft
from skippercast.seafloor.run import run
from tests._support import ROOT


def cell(x=0):
    return {'id': f'3310:{x}:0', 'reach': 'fixture-r01', 'tier': 0,
            'band_area_m2': 50000, 'reference_unknown_area_m2': 0}


def source(ident, resolution, year, geometry):
    return {'row': {'id': ident, 'resolution_m': resolution, 'year': year}, 'geometry': geometry}


class CoverageTests(unittest.TestCase):
    def test_mixed_grid_is_ranked_at_its_coarser_native_resolution(self):
        row = {'id': 'mixed', 'year': 2008, 'resolution_m': 2,
               'resolution_profile': {'fine_to_depth_m': 80, 'coarse_resolution_m': 5}}
        self.assertEqual(priority(row)[0], 5)
        self.assertEqual(priority({'id': 'fine', 'year': 2007, 'resolution_m': 2})[0], 2)

    def test_finer_then_newer_wins_and_duplicate_area_is_not_added(self):
        inputs = [source('coarse', 8, 2025, box(0, 0, 250, 250)),
                  source('older', 2, 2008, box(0, 0, 200, 250)),
                  source('newer', 2, 2020, box(0, 0, 100, 250))]
        result = classify_cells([cell()], inputs)[0]
        self.assertEqual(result['source_id'], 'newer')
        self.assertEqual(result['valid_area_m2'], 25000)
        self.assertEqual(result['tier'], 1)
        self.assertEqual(classify_cells([cell()], inputs+inputs)[0]['valid_area_m2'], 25000)

    def test_fine_sliver_does_not_hide_qualifying_coarse_source(self):
        inputs = [source('fine', 2, 2020, box(0, 0, 10, 250)),
                  source('coarse', 8, 2010, box(0, 0, 100, 250))]
        result = classify_cells([cell()], inputs)[0]
        self.assertEqual(result['source_id'], 'coarse')
        self.assertEqual(result['tier'], 1)
        self.assertEqual(classify_cells([cell()], inputs[:1])[0]['tier'], 0)
        self.assertEqual(classify_cells([cell()], [source('edge', 2, 2020, box(0, 0, 62.5, 250))])[0]['tier'], 1)
        self.assertEqual(classify_cells([cell()], [source('out', 2, 2020, box(300, 0, 500, 250))])[0]['valid_area_m2'], 0)

    def test_unknown_and_explicit_interpolation_masks_are_distinct(self):
        depth = np.array([[50, 91.44, 91.45, 0, -1, np.nan]])
        np.testing.assert_array_equal(valid_depth(depth, np.ones(depth.shape, bool)), [[1, 1, 0, 0, 0, 0]])
        np.testing.assert_array_equal(valid_depth(depth, np.ones(depth.shape, bool),
                                      np.array([[1, 0, 0, 0, 0, 0]], bool)), [[0, 1, 0, 0, 0, 0]])

    def test_native_footprint_keeps_holes_and_300ft_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'depth.tif'
            data = np.full((100, 100), 50, 'float32')
            data[20:30, 20:30] = np.nan
            data[50:60, 50:60] = 100
            with rasterio.open(path, 'w', driver='GTiff', width=100, height=100, count=1,
                 dtype='float32', crs=3310, transform=from_origin(0, 200, 2, 2), nodata=np.nan) as out:
                out.write(data, 1); out.set_band_description(1, 'depth_m_positive_down')
            t=Transformer.from_crs(3310, 4326, always_xy=True)
            bounds=[*t.transform(-100, -100), *t.transform(300, 300)]
            actual=footprint(path, bounds)
            self.assertAlmostEqual(actual.area, (10000-200)*4, places=5)
            self.assertFalse(actual.intersects(box(41, 141, 59, 159)))
            self.assertFalse(actual.intersects(box(101, 81, 119, 99)))

    def test_plane_and_bump_have_expected_terrain_and_holes_stay_unknown(self):
        yy, xx = np.indices((160, 160))
        plane = 50+.1*xx+.2*yy
        values=derivatives(plane, np.ones(plane.shape, bool), 2)
        self.assertAlmostEqual(values['vrm'][80,80], 0, places=12)
        self.assertAlmostEqual(values['bpi_fine_m'][80,80], 0, places=10)
        bump=50-10*np.exp(-((xx-80)**2+(yy-80)**2)/30)
        values=derivatives(bump, np.ones(bump.shape, bool), 2)
        self.assertGreater(values['bpi_fine_m'][80,80], 5)
        self.assertGreater(values['vrm'][80,80], 0)
        mask=np.ones(bump.shape,bool); mask[80,80]=False
        values=derivatives(bump,mask,2)
        self.assertTrue(np.isnan(values['vrm'][80,80]))
        self.assertTrue(np.isnan(values['bpi_fine_m'][80,81]))


class ReachRunTests(unittest.TestCase):
    def test_run_noop_corruption_and_withdrawn_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'catalog').mkdir(); (root/'var/seafloor/reference').mkdir(parents=True)
            (root/'dist/data').mkdir(parents=True)
            (root/'requirements-survey.txt').write_text('fixture')
            rules=json.loads((ROOT/'catalog/habitat-rules.json').read_text())
            rules['substrate_bindings']=[]
            (root/'catalog/habitat-rules.json').write_text(json.dumps(rules))
            (root/'dist/data/atlas.json').write_text('{"areas":[],"targets":[]}')
            (root/'catalog/survey.schema.json').write_text((ROOT/'catalog/survey.schema.json').read_text())
            native=root/'original.tif'
            with rasterio.open(native,'w',driver='GTiff',width=160,height=160,count=1,dtype='float32',
                crs=3310,transform=from_origin(-30,280,2,2),nodata=np.nan) as out:
                out.write(np.full((160,160),-50,'float32'),1)
            template=deepcopy(next(r for r in json.loads((ROOT/'catalog/surveys.json').read_text())['surveys'] if r['status']=='usable'))
            template.pop('adapter_review')
            template.update(id='fixture',url='https://pubs.usgs.gov/fixture.tif',archive_member='unknown',
                sha256=sha256(native),bytes=native.stat().st_size,derived_from=[],status='candidate')
            t=Transformer.from_crs(3310,4326,always_xy=True)
            bounds=[*t.transform(-50,-50),*t.transform(300,300)]
            receipt,_,_=ingest(template,bounds,root=root,local=native)
            row=qualify_row(template,receipt,rights_url='https://pubs.usgs.gov/fixture')
            # Stabilized manifest metadata has the same native COG output.
            manifest={'surveys':[row]}
            (root/'catalog/surveys.json').write_text(json.dumps(manifest))
            draft = root/'draft.json'
            draft.write_text(json.dumps({'row': row, 'adapter_review': receipt}))
            self.assertEqual(promote_draft(draft, root=root, rights_url='https://pubs.usgs.gov/fixture'), 'fixture')
            unchanged_manifest = (root/'catalog/surveys.json').read_bytes()
            bad = deepcopy(row); bad['license'] = 'unknown'
            draft.write_text(json.dumps({'row': bad, 'adapter_review': receipt}))
            with self.assertRaisesRegex(ValueError, 'rights'):
                promote_draft(draft, root=root, rights_url='https://pubs.usgs.gov/fixture')
            self.assertEqual((root/'catalog/surveys.json').read_bytes(), unchanged_manifest)
            (root/'catalog/reaches.json').write_text(json.dumps({'input_hash':'grid','reaches':[{'id':'fixture-r01'}]}))
            (root/'var/seafloor/reference/cells.json').write_text(json.dumps({'input_hash':'grid','cells':[cell()]}))
            (root/'var/seafloor/reference/run.json').write_text(json.dumps({'input_hash':'grid',
                'output_hashes':{'cells.json':sha256(root/'var/seafloor/reference/cells.json')}}))
            (root/'dist/data/seafloor-ledger.json').write_text(json.dumps({'reaches':[{'id':'fixture-r01','band_km2':.05}],
                'totals':{'band_km2':.05}}))
            first,unchanged=run('fixture-r01',root=root)
            self.assertFalse(unchanged)
            self.assertEqual(first['ledger_summary']['tier1_km2'],.05)
            self.assertEqual(first['ledger_summary']['selected_valid_km2'],.0625)
            self.assertEqual(first['ledger_summary']['tier2_km2'],0)
            with patch('skippercast.seafloor.run.footprint') as reading:
                second,unchanged=run('fixture-r01',root=root)
                self.assertTrue(unchanged); self.assertEqual(first,second); reading.assert_not_called()
            # Legal review/freshness changes must not recalculate seafloor physics.
            deferred, _ = run('fixture-r01', root=root, physical_only=True)
            self.assertEqual(deferred['ledger_summary']['tier2_km2'], 0)
            self.assertEqual(deferred['inputs']['screen']['reasons'], ['screen-deferred'])
            with patch('skippercast.seafloor.run.footprint') as reading, \
                 patch('skippercast.seafloor.run.build_candidates') as extracting:
                screened, unchanged = run('fixture-r01', root=root)
                self.assertFalse(unchanged)
                self.assertTrue(screened['physical_reused'])
                reading.assert_not_called(); extracting.assert_not_called()
            # A large native habitat failure preserves measured coverage.
            with patch('skippercast.seafloor.run.build_candidates',
                       side_effect=ValueError('Habitat window exceeds 20 million pixels')):
                with self.assertRaisesRegex(ValueError, '20 million pixels'):
                    run('fixture-r01', root=root, force=True)
            checkpoint = json.loads((root/'var/seafloor/reaches/fixture-r01/coverage-checkpoint.json').read_text())
            self.assertEqual(checkpoint['ledger_summary']['tier1_km2'], .05)
            self.assertEqual(checkpoint['ledger_summary']['tier2_km2'], 0)
            output=root/'var/seafloor/reaches/fixture-r01/cells.json'
            saved=output.read_bytes(); output.write_text('corrupt')
            with self.assertRaisesRegex(ValueError,'hash verification'):
                run('fixture-r01',root=root)
            output.write_bytes(saved)
            rules['rule_version']='fixture-rule-change'
            (root/'catalog/habitat-rules.json').write_text(json.dumps(rules))
            changed,unchanged=run('fixture-r01',root=root)
            self.assertFalse(unchanged)
            self.assertNotEqual(changed['input_hash'],first['input_hash'])
            manifest['surveys'][0]['status']='withdrawn'
            (root/'catalog/surveys.json').write_text(json.dumps(manifest))
            third,unchanged=run('fixture-r01',root=root)
            self.assertFalse(unchanged)
            self.assertEqual(third['ledger_summary']['tier1_km2'],0)
            # Native review can unlock private measurement without granting rights.
            private = qualify_row(dict(row, license='unknown'), receipt,
                                  rights_url='https://pubs.usgs.gov/fixture', physical_only=True)
            manifest['surveys'] = [private]
            (root/'catalog/surveys.json').write_text(json.dumps(manifest))
            measured, _ = run('fixture-r01', root=root, physical_only=True)
            self.assertEqual(measured['ledger_summary']['tier1_km2'], .05)
            self.assertEqual(measured['ledger_summary']['tier2_km2'], 0)
            self.assertEqual(measured['inputs']['sources'][0]['status'], 'physical-only')
            self.assertTrue(measured['publication_prohibited'])
            self.assertTrue((root/'var/seafloor/private-reaches/fixture-r01/candidates.geojson').exists())
            self.assertEqual(json.loads((root/'var/seafloor/reaches/fixture-r01/run.json').read_text())['ledger_summary']['tier1_km2'], 0)
            excluded, _ = run('fixture-r01', root=root)
            self.assertEqual(excluded['ledger_summary']['tier1_km2'], 0)
            self.assertEqual(excluded['inputs']['sources'], [])
            self.assertEqual(third['ledger_summary']['selected_valid_km2'],0)


if __name__=='__main__':
    unittest.main()

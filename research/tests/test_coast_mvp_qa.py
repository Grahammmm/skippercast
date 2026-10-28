"""Offline stdlib fixture controls; the C1 adapter has separate GIS controls."""
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import zlib

from research.scripts.coast_mvp import coast_qa as qa
from tests._support import ROOT

FIXTURE = ROOT / 'research/tests/fixtures/coast_mvp/qa/region.json'


class CoastQATest(unittest.TestCase):
    def test_fixture_stats_holes_and_measured_offset(self):
        with tempfile.TemporaryDirectory() as d:
            report = qa.packet(FIXTURE, Path(d)/'packet')
            s = report['segments'][0]
            self.assertEqual(report['status'], 'review_required')
            self.assertEqual(s['stats']['valid_cells'], 15)
            self.assertEqual(s['stats']['hole_cells'], 1)
            self.assertEqual(s['stats']['mean_elevation_m'], sum([-10]*7+[-13]*8)/15)
            self.assertEqual(s['hole_count'], 1)
            self.assertEqual(s['holes'], [dict(cells=1,pixel_bbox=[1,1,2,2],touches_boundary=False)])
            seam = s['seam_rms'][0]
            self.assertEqual((seam['overlap_cells'],seam['rms_m'],seam['mean_delta_m']), (3,3,3))
            self.assertEqual(json.loads((Path(d)/'packet/qa.json').read_text()), report)
            self.assertIn('NOT FOR NAVIGATION', (Path(d)/'packet/QA.txt').read_text())

    def test_missing_overlap_is_unavailable_not_zero(self):
        seam = qa.seams([('a', [[1,None]]),('b',[[None,2]])])[0]
        self.assertEqual(seam['status'], 'unavailable')
        self.assertIsNone(seam['rms_m'])
        self.assertEqual(seam['overlap_cells'], 0)

    def test_zero_error_requires_real_overlap(self):
        seam = qa.seams([('a',[[2]]),('b',[[2]])])[0]
        self.assertEqual(seam['status'], 'measured')
        self.assertEqual(seam['rms_m'], 0)
        self.assertEqual(seam['overlap_cells'], 1)

    def test_four_connected_holes_and_boundary_void(self):
        result = qa.holes([[None,1,1],[1,None,1],[1,1,1]])
        self.assertEqual(len(result), 2)
        self.assertEqual([x['touches_boundary'] for x in result], [True,False])

    def test_empty_and_single_cell(self):
        self.assertIsNone(qa.statistics([[None]])['mean_elevation_m'])
        self.assertEqual(qa.holes([[None]])[0]['cells'], 1)
        self.assertTrue(qa.hillshade([[1]],10).startswith(b'\x89PNG'))

    def test_png_decodes_and_nodata_is_transparent(self):
        rows, _ = qa.ascii_grid(FIXTURE.parent/'mosaic.asc')
        png = qa.hillshade(rows,10)
        self.assertEqual(png, qa.hillshade(rows,10))
        pos, compressed = 8, b''
        while pos < len(png):
            n = struct.unpack('>I',png[pos:pos+4])[0]
            tag, data = png[pos+4:pos+8],png[pos+8:pos+8+n]
            self.assertEqual(zlib.crc32(tag+data),struct.unpack('>I',png[pos+8+n:pos+12+n])[0])
            if tag == b'IHDR':
                self.assertEqual(struct.unpack('>IIBBBBB',data),(4,4,8,4,0,0,0))
            if tag == b'IDAT':
                compressed += data
            pos += n+12
        raw = zlib.decompress(compressed)
        self.assertEqual(len(raw),36)
        self.assertEqual(raw[13],0)
        self.assertEqual(raw[2],255)

    def test_cli_real_execution_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)/'packet'
            run = subprocess.run([sys.executable,'research/scripts/coast_mvp/coast_qa.py',
                                  '--region-config',str(FIXTURE),'--output',str(out)],
                                 cwd=ROOT,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(run.stdout)['segments'][0]['seam_rms'][0]['rms_m'],3)
            self.assertTrue((out/'fixture-hillshade.png').is_file())
            with self.assertRaises(FileExistsError):
                qa.packet(FIXTURE,out)

    def test_cli_package_form_and_no_regional_mode(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)/'packet'
            run = subprocess.run([sys.executable,'-m','research.scripts.coast_mvp.coast_qa',
                                  '--region-config',str(FIXTURE),'--output',str(out)],
                                 cwd=ROOT,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(run.stdout)['segments'][0]['seam_rms'][0]['rms_m'],3)
            for cmd in (['research/scripts/coast_mvp/coast_qa.py'],['-m','research.scripts.coast_mvp.coast_qa']):
                refused = subprocess.run([sys.executable,*cmd,'--regional','--region-config',str(FIXTURE),
                                          '--output',str(Path(d)/'regional')],cwd=ROOT,capture_output=True,text=True)
                self.assertEqual(refused.returncode,2)
                self.assertIn('unrecognized arguments: --regional',refused.stderr)
                self.assertFalse((Path(d)/'regional').exists())

    def test_bad_geometry_and_unsafe_identifier_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'bad.asc'
            p.write_text('ncols 1001\nnrows 1001\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n')
            with self.assertRaisesRegex(ValueError,'cap'):
                qa.ascii_grid(p)
        for value in ('../escape','a/b',''):
            with self.assertRaises(ValueError):
                qa.name(value)
        with self.assertRaises(ValueError):
            qa.local('https://example.invalid/grid.tif',ROOT)

    def test_one_region_packet_multiple_segments_and_duplicate_refused(self):
        doc = json.loads(FIXTURE.read_text())
        first = doc['segments'][0]
        first['mosaic'] = str(FIXTURE.parent/'mosaic.asc')
        for s in first['sources']:
            s['path'] = str(FIXTURE.parent/Path(s['path']))
        doc['segments'].append(dict(first,id='second'))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'region.json'
            p.write_text(json.dumps(doc))
            report = qa.packet(p,Path(d)/'packet')
            self.assertEqual(len(report['segments']),2)
            doc['segments'][1]['id']='fixture'
            p.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                qa.packet(p,Path(d)/'bad')
            self.assertFalse((Path(d)/'bad').exists())

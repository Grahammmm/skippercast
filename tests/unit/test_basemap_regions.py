"""The Chart basemap plan, manifest, publication and workflow (FE-10, design § 4)."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts.basemap import regions
from tests._support import ROOT, NOW
from tests.unit.test_cusp_shoreline import Response

LISTING = [{'key': '20261007.pmtiles', 'size': 138664957457, 'version': '4.15.2', 'b3sum': 'a' * 64},
           {'key': '20261008.pmtiles', 'size': 138703391160, 'version': '4.15.2', 'b3sum': 'b' * 64},
           {'key': 'notes.txt'}]


class FakeS3:
    def __init__(self, stored_bytes=None):
        self.calls, self.stored_bytes = [], stored_bytes

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.calls.append(('upload', key))
        self.metadata, self.size = ExtraArgs['Metadata'], Path(path).stat().st_size

    def head_object(self, Bucket, Key):
        self.calls.append(('head', Key))
        return {'ContentLength': self.stored_bytes or self.size, 'Metadata': self.metadata}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.calls.append(('put', Key))


class RegionPlanTests(unittest.TestCase):
    def test_boxes_are_the_bounds_of_every_active_and_preview_region(self):
        expected = {}
        for path in (ROOT / 'regions').glob('*/region.json'):
            region = json.loads(path.read_text())
            if region['status'] in ('active', 'preview'):
                expected[region['id']] = [float(v) for v in region['bounds']]
        boxes = regions.region_boxes()
        self.assertEqual({b['id']: b['bbox'] for b in boxes}, expected)
        self.assertIn('morro-bay', expected)

    def test_overview_holds_every_region_with_padding(self):
        boxes = regions.region_boxes()
        west, south, east, north = regions.overview_box(boxes)
        for box in boxes:
            w, s, e, n = box['bbox']
            tiny = 1e-9
            self.assertTrue(west <= w - 0.5 + tiny and south <= s - 0.5 + tiny and e + 0.5 <= east + tiny
                            and n + 0.5 <= north + tiny, box['id'])
        self.assertEqual(regions.overview_box([{'bbox': [-121.951, 34.95, -120.55, 35.849]}], pad=0),
                         [-121.96, 34.95, -120.55, 35.85])

    def test_detail_region_has_one_closed_ring_per_region(self):
        boxes = regions.region_boxes()
        polygons = regions.detail_region(boxes)['geometry']['coordinates']
        self.assertEqual(len(polygons), len(boxes))
        for (ring,), box in zip(polygons, boxes):
            self.assertEqual(ring[0], ring[-1])
            self.assertEqual([ring[0][0], ring[0][1], ring[2][0], ring[2][1]], box['bbox'])

    def test_bad_boxes_and_builds_are_refused(self):
        with self.assertRaises(ValueError):
            regions.check_bbox([-120, 35, -121, 36])
        with self.assertRaises(ValueError):
            regions.archive_key('2026-10-08')
        with self.assertRaises(ValueError):
            regions.plan('20260101', LISTING)
        with self.assertRaises(ValueError):
            regions.latest([{'key': 'notes.txt'}])

    def test_plan_names_the_dated_archive_and_disjoint_zooms(self):
        self.assertEqual(regions.latest(LISTING), '20261008')
        planned = regions.plan('20261008', LISTING)
        self.assertEqual(planned['key'], 'tiles/basemap/ca-coast-20261008.pmtiles')
        self.assertEqual(planned['source']['url'], 'https://build.protomaps.com/20261008.pmtiles')
        self.assertEqual(planned['source']['b3sum'], 'b' * 64)
        self.assertEqual(planned['overview']['maxzoom'] + 1, planned['detail']['minzoom'])
        self.assertEqual(planned['detail']['maxzoom'], 14)


class ListingTests(unittest.TestCase):
    def test_listing_comes_from_its_exact_host_and_is_capped(self):
        body = json.dumps(LISTING).encode()
        with patch.object(regions, 'urlopen', return_value=Response(regions.BUILDS, body)):
            self.assertEqual(regions.listing(), LISTING)
        with patch.object(regions, 'urlopen', return_value=Response('https://example.com/builds.json', body)):
            with self.assertRaises(ValueError):
                regions.listing()
        with patch.object(regions, 'urlopen', return_value=Response(regions.BUILDS, bytes(regions.MAX_LISTING_BYTES + 1))):
            with self.assertRaises(ValueError):
                regions.listing()


class ManifestAndPublishTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.planned = regions.plan('20261008', LISTING)
        self.archive = self.dir / 'ca-coast-20261008.pmtiles'
        self.archive.write_bytes(b'PMTiles\x03' + bytes(4096))

    def test_manifest_records_size_hash_source_and_attribution(self):
        document = regions.manifest(self.planned, self.archive, 36.4, now=NOW)
        self.assertEqual(document['bytes'], 4104)
        self.assertEqual(document['sha256'], regions.sha256(self.archive))
        self.assertEqual(document['build_seconds'], 36)
        self.assertEqual(document['source']['build'], '20261008')
        self.assertEqual(document['attribution'], '© OpenStreetMap contributors, © Protomaps')
        self.assertEqual(document['built_at'], '2026-09-28T12:00:00Z')
        with self.assertRaises(ValueError):
            regions.manifest(self.planned, self.dir / 'other.pmtiles', 1)

    def test_publish_reads_the_archive_back_before_moving_the_manifest(self):
        document = regions.manifest(self.planned, self.archive, 1, now=NOW)
        s3 = FakeS3()
        regions.publish(s3, 'bucket', self.archive, document)
        key = 'tiles/basemap/ca-coast-20261008.pmtiles'
        self.assertEqual(s3.calls, [('upload', key), ('head', key), ('put', 'tiles/basemap/manifest.json')])
        short = FakeS3(stored_bytes=10)
        with self.assertRaises(RuntimeError):
            regions.publish(short, 'bucket', self.archive, document)
        self.assertNotIn(('put', 'tiles/basemap/manifest.json'), short.calls)


class WorkflowTests(unittest.TestCase):
    def test_dispatch_only_pinned_and_least_privilege(self):
        text = (ROOT / '.github/workflows/basemap.yml').read_text()
        triggers = text.split('\non:\n', 1)[1].split('\npermissions:', 1)[0]
        self.assertEqual(re.findall(r'^  (\w+):', triggers, re.M), ['workflow_dispatch'])
        self.assertNotIn('pull_request', text)
        self.assertIn('\npermissions: {}\n', text)
        self.assertIn("runs-on: ${{ vars.DATA_RUNNER || 'ubuntu-latest' }}", text)
        self.assertIn("if: github.ref == 'refs/heads/main'", text)
        for ref in re.findall(r'uses:\s*(\S+)', text):
            self.assertRegex(ref, r'@[0-9a-f]{40}$')
        self.assertRegex(text, r'go-pmtiles@v\d+\.\d+\.\d+')
        self.assertIn('secrets.R2_PUBLISH_TOKEN || secrets.CLOUDFLARE_API_TOKEN', text)


if __name__ == '__main__':
    unittest.main()

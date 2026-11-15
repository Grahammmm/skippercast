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


class Missing(Exception):
    """What boto3's head_object raises for an absent key (a ClientError with code 404)."""
    response = {'Error': {'Code': '404'}}


class Precondition(Exception):
    """What boto3 raises when R2 refuses a PUT with `If-None-Match: *` because the key exists (412)."""
    response = {'Error': {'Code': 'PreconditionFailed'}, 'ResponseMetadata': {'HTTPStatusCode': 412}}


class FakeS3:
    """R2 as the publisher sees it; a PUT with IfNoneMatch='*' is refused at commit while the key holds an object."""
    def __init__(self, stored_bytes=None, existing=None):
        self.calls, self.stored_bytes = [], stored_bytes
        self.objects = dict(existing or {})  # key -> head_object answer

    def head_object(self, Bucket, Key):
        self.calls.append(('head', Key))
        if Key not in self.objects:
            raise Missing(Key)
        return self.objects[Key]

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, Metadata=None, **kwargs):
        if Key.endswith('manifest.json'):
            self.calls.append(('put', Key))
            return
        self.calls.append(('create', Key))
        if IfNoneMatch != '*':
            raise AssertionError('an archive PUT must be create-only (IfNoneMatch="*")')
        if Key in self.objects:
            raise Precondition(Key)
        self.objects[Key] = {'ContentLength': self.stored_bytes or len(Body.read()), 'Metadata': Metadata}


class RacingS3(FakeS3):
    """Another publisher creates `racer` at the key right after our HEAD sees it absent."""
    def __init__(self, racer):
        super().__init__()
        self.racer = racer

    def head_object(self, Bucket, Key):
        try:
            return super().head_object(Bucket, Key)
        except Missing:
            self.objects[Key] = self.racer
            raise


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
        # R4-SC-08: the published key names the content; the local file keeps the date-only name.
        self.assertEqual(document['key'], f"tiles/basemap/ca-coast-20261008-{document['sha256'][:16]}.pmtiles")
        self.assertEqual(document['build_seconds'], 36)
        self.assertEqual(document['source']['build'], '20261008')
        self.assertEqual(document['attribution'], '© OpenStreetMap contributors, © Protomaps')
        self.assertEqual(document['built_at'], '2026-09-28T12:00:00Z')
        with self.assertRaises(ValueError):
            regions.manifest(self.planned, self.dir / 'other.pmtiles', 1)
        with self.assertRaises(ValueError):
            regions.content_key('20261008', 'A' * 64)

    def test_publish_reads_the_archive_back_before_moving_the_manifest(self):
        document = regions.manifest(self.planned, self.archive, 1, now=NOW)
        s3 = FakeS3()
        self.assertIn(document['key'], regions.publish(s3, 'bucket', self.archive, document))
        key = document['key']
        self.assertEqual(s3.calls, [('head', key), ('create', key), ('head', key), ('put', 'tiles/basemap/manifest.json')])
        short = FakeS3(stored_bytes=10)
        with self.assertRaisesRegex(RuntimeError, 'read-back mismatch'):
            regions.publish(short, 'bucket', self.archive, document)
        self.assertNotIn(('put', 'tiles/basemap/manifest.json'), short.calls)

    def test_publish_never_overwrites_an_existing_key(self):
        document = regions.manifest(self.planned, self.archive, 1, now=NOW)
        key, put = document['key'], ('put', 'tiles/basemap/manifest.json')
        other = FakeS3(existing={key: {'ContentLength': document['bytes'], 'Metadata': {'sha256': 'f' * 64}}})
        with self.assertRaisesRegex(RuntimeError, 'already holds other bytes; not overwritten'):
            regions.publish(other, 'bucket', self.archive, document)
        self.assertEqual(other.calls, [('head', key)], 'no upload over another archive, no manifest')
        # A rerun after a failed manifest write: the same bytes are there, so only the manifest is written.
        same = FakeS3(existing={key: {'ContentLength': document['bytes'], 'Metadata': {'sha256': document['sha256']}}})
        regions.publish(same, 'bucket', self.archive, document)
        self.assertEqual(same.calls, [('head', key), put])
        # A manifest that does not name its archive's content key (a date-only key from before R4-SC-08) uploads nothing.
        for stale in ({**document, 'key': 'tiles/basemap/ca-coast-20261008.pmtiles'}, {**document, 'sha256': 'e' * 64}):
            s3 = FakeS3()
            with self.assertRaisesRegex(RuntimeError, 'not the content key'):
                regions.publish(s3, 'bucket', self.archive, stale)
            self.assertEqual(s3.calls, [])

    def test_publish_never_overwrites_an_object_created_after_its_head(self):
        # R2 refuses the create-only PUT at commit (412), so the racer's object stays and the manifest does not move.
        document = regions.manifest(self.planned, self.archive, 1, now=NOW)
        key, put = document['key'], ('put', 'tiles/basemap/manifest.json')
        racer = {'ContentLength': 4096, 'Metadata': {'sha256': 'f' * 64}}
        raced = RacingS3(racer)
        with self.assertRaisesRegex(RuntimeError, 'already holds other bytes; not overwritten'):
            regions.publish(raced, 'bucket', self.archive, document)
        self.assertIs(raced.objects[key], racer, 'the conflicting object is preserved')
        self.assertEqual(raced.calls, [('head', key), ('create', key), ('head', key)])
        # The racer wrote these same bytes (another run of this build, or our own lost acknowledgment): manifest written.
        same = RacingS3({'ContentLength': document['bytes'], 'Metadata': {'sha256': document['sha256']}})
        regions.publish(same, 'bucket', self.archive, document)
        self.assertEqual(same.calls, [('head', key), ('create', key), ('head', key), put])

    def test_an_archive_above_the_single_put_limit_writes_nothing(self):
        document = regions.manifest(self.planned, self.archive, 1, now=NOW)
        s3 = FakeS3()
        with patch.object(regions, 'MAX_SINGLE_PUT', document['bytes'] - 1):
            with self.assertRaisesRegex(RuntimeError, 'single PUT limit; nothing published'):
                regions.publish(s3, 'bucket', self.archive, document)
        self.assertEqual(s3.calls, [('head', document['key'])])

    def test_head_errors_other_than_absence_stop_publication(self):
        document = regions.manifest(self.planned, self.archive, 1, now=NOW)

        class Denied(FakeS3):
            def head_object(self, Bucket, Key):
                raise PermissionError('403')
        with self.assertRaises(PermissionError):
            regions.publish(Denied(), 'bucket', self.archive, document)

        class Refused(FakeS3):  # a PUT error other than 412 (e.g. 409 bucket lock) stops publication too
            def put_object(self, Bucket, Key, Body, **kwargs):
                self.calls.append(('create', Key))
                raise PermissionError('409')
        refused = Refused()
        with self.assertRaises(PermissionError):
            regions.publish(refused, 'bucket', self.archive, document)
        self.assertEqual(refused.calls, [('head', document['key']), ('create', document['key'])])


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

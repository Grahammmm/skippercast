"""SC-PERF-REEFDIET-1: the slim reef file the brief reads (attributes + verdicts, no outlines), its size budget and its publication."""
from datetime import datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import publish, slim
from skippercast.seafloor.io import sha256
from tests.gis.test_seafloor_publish import Bucket, bundle
from tests._support import NOW

VERDICT = {'inside': False, 'name': None, 'distanceM': None, 'screened': True}


def feature(i, **extra):
    props = {'id': f'reef-{i}', 'region': 'morro-bay', 'tier': 2, 'status': 'habitat', 'exportable': True,
             'screen': {'status': 'pass', 'checks': ['land', 'depth']}, 'waypoint': {'longitude': -121, 'latitude': 35},
             'terrain': {'grade': 'A', 'score': 80}, 'fit': {'lingcod': 3}, 'depth_min_ft': 40, 'depth_max_ft': 90,
             'source_ids': ['s'], 'source_urls': ['https://example.test'], 'protected_place': dict(VERDICT),
             'dropped_only_in_full': 'x'*500, 'evidence': [{'family': 'f'}], **extra}
    ring = [[-121, 35], [-120.9, 35], [-120.9, 35.1], [-121, 35]]
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [ring]}, 'properties': props}


class SlimFileTests(unittest.TestCase):
    def test_slim_keeps_only_the_listed_properties_and_no_outline(self):
        out = slim.slim_features([feature(1), feature(2)])
        self.assertEqual(len(out), 2)
        for f in out:
            self.assertIsNone(f['geometry'])
            self.assertTrue(set(f['properties']) <= set(slim.SLIM_FIELDS))
            self.assertNotIn('dropped_only_in_full', f['properties'])
            self.assertNotIn('evidence', f['properties'])
            self.assertEqual(f['properties']['screen'], {'status': 'pass'})
            self.assertEqual(f['properties']['protected_place'], VERDICT)

    def test_the_list_is_the_one_the_loader_test_uses_and_is_sorted_by_nothing_extra(self):
        fields = json.loads(Path(slim.__file__).with_name('slim_fields.json').read_text())['properties']
        self.assertEqual(list(slim.SLIM_FIELDS), fields)
        self.assertEqual(len(fields), len(set(fields)))
        self.assertNotIn('geometry', fields)

    def test_a_reef_without_a_verdict_stops_the_slim_file(self):
        bad = feature(3); del bad['properties']['protected_place']
        with self.assertRaisesRegex(ValueError, 'verdict'):
            slim.slim_features([feature(1), bad])

    def test_written_file_is_hashed_in_the_manifest_fields_and_names_its_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            fields = slim.write_slim(tmp, region='morro-bay', expires_at='2030-01-01T00:00:00+00:00', export_sha256='a'*64,
                                     protected={'fingerprint': 'ps2-x', 'version': 2}, export_features=[feature(1), feature(2)])
            path = Path(tmp)/fields['slim_file']
            self.assertEqual(fields['slim_file'], f'habitat-slim-{sha256(path)[:16]}.geojson.gz')
            self.assertTrue(slim.SLIM_NAME.fullmatch(fields['slim_file']))
            self.assertEqual(fields['slim_sha256'], sha256(path))
            self.assertEqual(fields['slim_bytes'], path.stat().st_size)
            data = json.loads(gzip.decompress(path.read_bytes()))
            self.assertEqual(fields['slim_decoded_bytes'], len(gzip.decompress(path.read_bytes())))
            self.assertEqual((data['slim_of'], data['protected_screen']['fingerprint'], data['region']), ('a'*64, 'ps2-x', 'morro-bay'))
            self.assertEqual(path.read_bytes(), gzip.compress(gzip.decompress(path.read_bytes()), mtime=0))

    def test_no_verdicts_means_no_slim_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'habitat-slim-0123456789abcdef.geojson.gz').write_bytes(b'an earlier build')
            self.assertEqual(slim.write_slim(tmp, region='morro-bay', expires_at='x', export_sha256='a'*64, protected=None,
                                             export_features=[feature(1)]), {})
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_size_budget(self):
        # The real morro-bay export (3064 reefs) gave 363,453 bytes when this budget was set; a file over it is not published.
        self.assertEqual(slim.SLIM_MAX_BYTES, 450_000)
        with tempfile.TemporaryDirectory() as tmp, patch.object(slim, 'SLIM_MAX_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'budget'):
                slim.write_slim(tmp, region='morro-bay', expires_at='x', export_sha256='a'*64, protected={'fingerprint': 'p'},
                                export_features=[feature(i) for i in range(50)])
            self.assertEqual(list(Path(tmp).iterdir()), [])


def slim_bundle(root, reefs=(1,)):
    folder, manifest = bundle(root)
    fields = slim.write_slim(folder, region='morro-bay', expires_at=manifest['expires_at'], export_sha256=manifest['export_sha256'],
                             protected={'fingerprint': 'ps2-x'}, export_features=[feature(i) for i in reefs])
    manifest.update(fields)
    atomic_json(folder/'manifest.json', manifest)
    return folder, manifest


class PreconditionFailed(Exception):
    pass


class R2(Bucket):
    """The publication tests' bucket, plus what R2 also does: object metadata and an ETag on GET, conditional PUT (IfMatch),
    and a record of every delete."""

    def __init__(self):
        super().__init__()
        self.deleted, self.log = [], []

    def etag(self, key):
        return '"' + hashlib.md5(self.objects[key]).hexdigest() + '"'

    def get_object(self, *, Bucket, Key):
        self.log.append(('get', Key))
        got = super().get_object(Bucket=Bucket, Key=Key)
        return {**got, 'Metadata': dict(self.metadata.get(Key, {}).get('Metadata') or {}), 'ETag': self.etag(Key)}

    def put_object(self, *, Bucket, Key, Body, IfMatch=None, **kwargs):
        if IfMatch is not None and (Key not in self.objects or self.etag(Key) != IfMatch):
            raise PreconditionFailed(Key)
        self.log.append(('put', Key))
        return super().put_object(Bucket=Bucket, Key=Key, Body=Body, **kwargs)

    def delete_objects(self, *, Bucket, Delete):
        self.deleted += [item['Key'] for item in Delete['Objects']]
        return super().delete_objects(Bucket=Bucket, Delete=Delete)


CONTROL = 'tiles/seafloor/manifest-morro-bay.json'
PREFIX = 'tiles/seafloor/regions/morro-bay/'
ARCHIVE = 'tiles/seafloor/seafloor-morro-bay.pmtiles'


def serve(s3, key, now=NOW):
    """(status, bytes) that server/feeds.ts serveFeed answers for a seafloor export, slim file or archive on this bucket:
    the live manifest must be ready, unexpired, for this region and name this file, and the object's sha256 metadata must
    be the manifest's hash for it."""
    export = re.fullmatch(r'tiles/seafloor/regions/([a-z0-9-]+)/(habitat-export\.geojson(?:\.gz)?|habitat-slim-[a-f0-9]{16}\.geojson\.gz)', key)
    archive = re.fullmatch(r'tiles/seafloor/seafloor-([a-z0-9-]+)\.pmtiles', key)
    if not export and not archive:
        return 404, None
    region = (export or archive).group(1)
    is_slim = bool(export) and export.group(2).startswith('habitat-slim-')
    try:
        manifest = json.loads(s3.objects[f'tiles/seafloor/manifest-{region}.json'])
    except (KeyError, ValueError):
        manifest = {}
    expected = manifest.get('slim_sha256' if is_slim else 'export_sha256' if export else 'archive_sha256')
    named = not export or manifest.get('slim_file' if is_slim else 'export_file') == export.group(2)
    try:
        live = datetime.fromisoformat(manifest['expires_at']) > now
    except (KeyError, TypeError, ValueError):
        live = False
    if manifest.get('status') != 'ready' or manifest.get('region') != region or not named or not live \
            or not re.fullmatch('[a-f0-9]{64}', expected or ''):
        return 503, None
    if key not in s3.objects:
        return 404, None
    if (s3.metadata[key].get('Metadata') or {}).get('sha256') != expected:
        return 503, None
    return 200, s3.objects[key]


def read_back_before_manifest(s3, key):
    """The key was PUT, then read back, and only after that was the live manifest written (R2.log order)."""
    put = s3.log.index(('put', key))
    return s3.log.index(('get', key), put) < s3.log.index(('put', CONTROL), put)


class SlimPublicationTests(unittest.TestCase):
    def test_first_publication_serves_the_slim_file_at_its_content_addressed_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, manifest = slim_bundle(tmp)
            s3 = R2()
            publish.publish_bundle(s3, 'b', folder, now=NOW)
            key = PREFIX + manifest['slim_file']
            self.assertEqual(manifest['slim_file'], f"habitat-slim-{manifest['slim_sha256'][:16]}.geojson.gz")
            self.assertEqual(s3.objects[key], (folder/manifest['slim_file']).read_bytes())
            self.assertEqual(s3.metadata[key]['CacheControl'], 'no-store')
            self.assertEqual(s3.metadata[key]['ContentType'], 'application/gzip')
            self.assertEqual(s3.metadata[key]['Metadata']['sha256'], manifest['slim_sha256'])
            self.assertEqual(s3.metadata[PREFIX + 'habitat-export.geojson']['CacheControl'], s3.metadata[key]['CacheControl'])
            self.assertEqual(s3.puts[0], key)                        # uploaded before anything else
            self.assertEqual(s3.puts.count(key), 1)                  # and never again by sync()
            self.assertTrue(read_back_before_manifest(s3, key))
            self.assertEqual(json.loads(s3.objects[CONTROL])['slim_file'], manifest['slim_file'])
            for served in (key, PREFIX + 'habitat-export.geojson', ARCHIVE):
                self.assertEqual(serve(s3, served)[0], 200, served)
            self.assertNotIn(manifest['slim_file'], json.loads(s3.objects[PREFIX + '.r2-sync.json']))
            self.assertEqual(s3.deleted, [])

    def test_changed_or_unlisted_slim_file_never_uploads(self):
        for case in ('changed', 'path', 'name-not-its-hash', 'old-fixed-name', 'unlisted-extra', 'hash-missing'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                folder, manifest = slim_bundle(tmp)
                name = manifest['slim_file']
                if case == 'changed': (folder/name).write_bytes(b'corrupt')
                if case == 'path': manifest['slim_file'] = '../' + name
                other = {'name-not-its-hash': 'habitat-slim-0000000000000000.geojson.gz', 'old-fixed-name': 'habitat-slim.geojson.gz'}.get(case)
                if other:
                    (folder/name).rename(folder/other)
                    manifest['slim_file'] = other
                if case == 'unlisted-extra': (folder/'other.geojson.gz').write_bytes(b'x')
                if case == 'hash-missing': del manifest['slim_sha256']
                atomic_json(folder/'manifest.json', manifest)
                s3 = R2()
                with self.assertRaises(ValueError):
                    publish.publish_bundle(s3, 'b', folder, now=NOW)
                self.assertEqual(s3.puts, [])

    def test_a_slim_file_the_manifest_does_not_name_is_an_unexpected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, manifest = bundle(tmp)
            (folder/'habitat-slim-0123456789abcdef.geojson.gz').write_bytes(b'x')
            s3 = R2()
            with self.assertRaisesRegex(ValueError, 'Unexpected file'):
                publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(s3.puts, [])

    def live_release(self, tmp, *, export_changed=False):
        """A bucket serving a READY release (manifest, export, archive, slim file), and the next bundle: same export,
        archive and ledger with a new slim file (or, with export_changed, a new full export too)."""
        old_folder, old_manifest = slim_bundle(tmp)
        s3 = R2()
        publish.publish_bundle(s3, 'b', old_folder, now=NOW)
        self.assertEqual(serve(s3, PREFIX + old_manifest['slim_file'])[0], 200)
        new_folder = Path(tmp)/'next'
        new_folder.mkdir()
        for path in old_folder.iterdir():
            if path.name != old_manifest['slim_file']:
                (new_folder/path.name).write_bytes(path.read_bytes())
        manifest = dict(old_manifest)
        if export_changed:
            atomic_json(new_folder/'habitat-export.geojson', {'region': 'morro-bay', 'features': [], 'changed': True})
            manifest['export_sha256'] = sha256(new_folder/'habitat-export.geojson')
        manifest.update(slim.write_slim(new_folder, region='morro-bay', expires_at=manifest['expires_at'],
                                        export_sha256=manifest['export_sha256'], protected={'fingerprint': 'ps2-x'},
                                        export_features=[feature(1), feature(2)]))
        self.assertNotEqual(manifest['slim_file'], old_manifest['slim_file'])
        atomic_json(new_folder/'manifest.json', manifest)
        live = {'objects': dict(s3.objects), 'metadata': {k: dict(v) for k, v in s3.metadata.items()},
                'manifest': old_manifest, 'new': manifest}
        s3.puts.clear(); s3.gets.clear()
        return s3, live, new_folder

    def assert_previous_release_served(self, s3, live):
        old, new = live['manifest'], live['new']
        self.assertEqual(s3.objects[CONTROL], live['objects'][CONTROL])          # the very same manifest bytes
        self.assertEqual(json.loads(s3.objects[CONTROL])['status'], 'ready')
        self.assertEqual(serve(s3, PREFIX + 'habitat-export.geojson'), (200, live['objects'][PREFIX + 'habitat-export.geojson']))
        self.assertEqual(serve(s3, PREFIX + old['slim_file']), (200, live['objects'][PREFIX + old['slim_file']]))
        self.assertEqual(serve(s3, ARCHIVE), (200, live['objects'][ARCHIVE]))
        self.assertEqual(serve(s3, PREFIX + new['slim_file'])[0], 503)          # staged, never named, never served
        self.assertEqual(s3.deleted, [])
        for key, value in live['objects'].items():                              # nothing deleted or rewritten
            self.assertEqual(s3.objects.get(key), value, key)
            self.assertEqual(s3.metadata.get(key), live['metadata'][key], key)

    def failing(self, s3, live, step):
        """Make one publication step fail the way R2 can: the new slim PUT (rejected, or committed with the reply lost), its
        read-back (an error, wrong bytes, missing sha256 metadata), or the one manifest write."""
        new_key = PREFIX + live['new']['slim_file']
        real_put, real_get = s3.put_object, s3.get_object

        def put(**kwargs):
            if kwargs['Key'] == new_key and step == 'slim PUT rejected':
                raise OSError('R2 PUT failed')
            if kwargs['Key'] == new_key and step == 'slim PUT metadata lost':
                kwargs = {k: v for k, v in kwargs.items() if k != 'Metadata'}
            if kwargs['Key'] == CONTROL and step == 'manifest write':
                raise OSError('R2 PUT failed')
            result = real_put(**kwargs)
            if kwargs['Key'] == new_key and step == 'slim PUT committed, reply lost':
                raise TimeoutError('PUT committed; response lost')
            return result

        def get(*, Bucket, Key):
            got = real_get(Bucket=Bucket, Key=Key)
            if Key == new_key and Key in s3.puts:
                if step == 'slim read-back error':
                    raise OSError('R2 GET failed')
                if step == 'slim checksum':
                    got = {**got, 'Body': io.BytesIO(b'bad read-back')}
            return got
        s3.put_object, s3.get_object = put, get

    STEPS = ('slim PUT rejected', 'slim PUT committed, reply lost', 'slim PUT metadata lost', 'slim read-back error',
             'slim checksum', 'manifest write')

    def test_a_failed_step_leaves_the_previous_ready_release_served(self):
        for export_changed in (False, True):
            for step in self.STEPS:
                if export_changed and step == 'manifest write':
                    continue   # with a changed full export the existing held publication follows; not a slim step
                with self.subTest(step=step, export_changed=export_changed), tempfile.TemporaryDirectory() as tmp:
                    s3, live, folder = self.live_release(tmp, export_changed=export_changed)
                    self.failing(s3, live, step)
                    with self.assertRaises(Exception):
                        publish.publish_bundle(s3, 'b', folder, now=NOW)
                    if step != 'manifest write':
                        self.assertNotIn(CONTROL, s3.puts)       # no hold, no status=updating, no restore
                    self.assertEqual([k for k in s3.puts if k != PREFIX + live['new']['slim_file'] and k != CONTROL], [])
                    self.assert_previous_release_served(s3, live)

    def test_a_retry_after_a_failure_publishes_and_reuses_the_verified_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            s3, live, folder = self.live_release(tmp)
            self.failing(s3, live, 'manifest write')
            with self.assertRaises(OSError):
                publish.publish_bundle(s3, 'b', folder, now=NOW)
            del s3.put_object, s3.get_object       # the failure is over
            s3.puts.clear()
            publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(s3.puts, [CONTROL])                    # the verified slim object is not uploaded again
            self.assertEqual(serve(s3, PREFIX + live['new']['slim_file'])[0], 200)

    def test_a_successful_publish_writes_one_manifest_and_keeps_the_old_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            s3, live, folder = self.live_release(tmp)
            old, new = live['manifest'], live['new']
            publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(s3.puts, [PREFIX + new['slim_file'], CONTROL])   # no sync, no hold, no export or archive rewrite
            switched = json.loads(s3.objects[CONTROL])
            self.assertEqual(switched, {**json.loads(live['objects'][CONTROL]), **{k: new[k] for k in publish.SLIM_MANIFEST_FIELDS}})
            self.assertEqual(serve(s3, PREFIX + new['slim_file']), (200, (folder/new['slim_file']).read_bytes()))
            self.assertEqual(serve(s3, PREFIX + 'habitat-export.geojson'), (200, live['objects'][PREFIX + 'habitat-export.geojson']))
            self.assertEqual(serve(s3, ARCHIVE)[0], 200)
            self.assertEqual(s3.deleted, [])
            for key, value in live['objects'].items():
                if key != CONTROL:
                    self.assertEqual(s3.objects[key], value, key)   # old objects, the old slim file included, still exist
            self.assertIn(PREFIX + old['slim_file'], s3.objects)

    def test_a_publish_interrupted_at_any_write_leaves_a_servable_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            s3, live, folder = self.live_release(tmp)
            real, states = s3.put_object, []

            def servable():
                named = json.loads(s3.objects[CONTROL])
                return [serve(s3, PREFIX + 'habitat-export.geojson')[0], serve(s3, PREFIX + named['slim_file'])[0], serve(s3, ARCHIVE)[0]]

            def put(**kwargs):
                states.append(servable())          # interrupted just before this write
                result = real(**kwargs)
                states.append(servable())          # interrupted just after it
                return result
            s3.put_object = put
            publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(len(states), 4)
            self.assertTrue(all(state == [200, 200, 200] for state in states), states)

    def test_a_release_committed_by_someone_else_meanwhile_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            s3, live, folder = self.live_release(tmp)
            real, theirs = s3.get_object, json.dumps({**live['manifest'], 'built_at': 'another publisher'}).encode()

            def get(*, Bucket, Key):
                got = real(Bucket=Bucket, Key=Key)
                if Key == CONTROL:
                    s3.objects[CONTROL] = theirs      # committed between our read and our write
                return got
            s3.get_object = get
            with self.assertRaises(PreconditionFailed):
                publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(s3.objects[CONTROL], theirs)

    def test_with_a_changed_full_export_the_slim_file_is_verified_before_the_held_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            s3, live, folder = self.live_release(tmp, export_changed=True)
            new = live['new']
            publish.publish_bundle(s3, 'b', folder, now=NOW)
            new_key = PREFIX + new['slim_file']
            self.assertEqual(s3.puts[0], new_key)
            self.assertEqual(s3.puts.count(new_key), 1)              # sync() never writes it (it would drop the sha256 metadata)
            self.assertTrue(read_back_before_manifest(s3, new_key))
            self.assertEqual(json.loads(s3.objects[CONTROL]), new)
            for key in (new_key, PREFIX + 'habitat-export.geojson', ARCHIVE):
                self.assertEqual(serve(s3, key)[0], 200, key)
            self.assertIn(PREFIX + live['manifest']['slim_file'], s3.objects)   # the old slim object is kept
            self.assertEqual(s3.deleted, [])


class BuildTests(unittest.TestCase):
    def test_build_writes_the_slim_file_beside_the_full_export_when_verdicts_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            geometry = {'type': 'Polygon', 'coordinates': [[[-121, 35], [-120.99, 35], [-120.99, 35.01], [-121, 35.01], [-121, 35]]]}
            properties = {'id': 'test-reef', 'terrain': {'grade': 'A', 'score': 90}, 'fit': {'lingcod': 3}, 'source_ids': ['native'],
                          'screen': {'status': 'pass'}, 'depth_min_ft': 90, 'depth_max_ft': 120}
            layers = {'cells': [], 'habitat': [{'type': 'Feature', 'geometry': geometry, 'properties': publish.flat_properties(properties)}]}
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reference': {}, 'reaches': []})
            atomic_json(root/'catalog/surveys.json', {'surveys': [{'id': 'native', 'url': 'https://example.test/original'}]})
            def archive(tool, layers, path, **kwargs):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'PMTiles\x03fixture')
            def stamp(root_, region, exports):
                for f in exports: f['properties']['protected_place'] = dict(VERDICT)
                return {'fingerprint': 'ps2-test', 'version': 2}
            for verdicts in (True, False):
                with self.subTest(verdicts=verdicts), \
                     patch.object(publish, 'region_layers', return_value=(layers, {}, NOW + __import__('datetime').timedelta(days=1))), \
                     patch('scripts.build_map_tiles.build_vector_archive', side_effect=archive), \
                     patch.object(publish, 'stamp_protected', side_effect=stamp if verdicts else lambda *a: None):
                    folder, manifest = publish.build('morro-bay', root=root, tool='fixture', now=NOW)
                    full = json.loads(gzip.decompress((folder/manifest['export_file']).read_bytes()))
                    if not verdicts:
                        self.assertNotIn('slim_file', manifest)
                        self.assertEqual(list(folder.glob('habitat-slim*')), [])
                        continue
                    path = folder/manifest['slim_file']
                    self.assertEqual(manifest['slim_sha256'], sha256(path))
                    self.assertEqual(manifest['export_sha256'], sha256(folder/manifest['export_file']))
                    data = json.loads(gzip.decompress(path.read_bytes()))
                    self.assertEqual(data['slim_of'], manifest['export_sha256'])
                    self.assertEqual(data['protected_screen'], full['protected_screen'])
                    self.assertEqual(data['expires_at'], full['expires_at'])
                    f = data['features'][0]
                    self.assertIsNone(f['geometry'])
                    self.assertEqual(f['properties']['id'], 'test-reef')
                    self.assertEqual(f['properties']['waypoint'], full['features'][0]['properties']['waypoint'])
                    self.assertEqual(f['properties']['protected_place'], VERDICT)
                    self.assertLess(path.stat().st_size, (folder/manifest['export_file']).stat().st_size + 1)
                    self.assertEqual({p.name for p in folder.iterdir()}, {'seafloor-morro-bay.pmtiles', 'ledger.json', 'manifest.json',
                                                                             manifest['export_file'], manifest['slim_file']})


if __name__ == '__main__':
    unittest.main()

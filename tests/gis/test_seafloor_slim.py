"""SC-PERF-REEFDIET-1: the slim reef file the brief reads (attributes + verdicts, no outlines), its size budget and its publication."""
import gzip
import hashlib
import json
from pathlib import Path
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
            path = Path(tmp)/'habitat-slim.geojson.gz'
            self.assertEqual(fields['slim_file'], path.name)
            self.assertEqual(fields['slim_sha256'], sha256(path))
            self.assertEqual(fields['slim_bytes'], path.stat().st_size)
            data = json.loads(gzip.decompress(path.read_bytes()))
            self.assertEqual(fields['slim_decoded_bytes'], len(gzip.decompress(path.read_bytes())))
            self.assertEqual((data['slim_of'], data['protected_screen']['fingerprint'], data['region']), ('a'*64, 'ps2-x', 'morro-bay'))
            self.assertEqual(path.read_bytes(), gzip.compress(gzip.decompress(path.read_bytes()), mtime=0))

    def test_no_verdicts_means_no_slim_file(self):
        with tempfile.TemporaryDirectory() as tmp:
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


def slim_bundle(root):
    folder, manifest = bundle(root)
    fields = slim.write_slim(folder, region='morro-bay', expires_at=manifest['expires_at'], export_sha256=manifest['export_sha256'],
                             protected={'fingerprint': 'ps2-x'}, export_features=[feature(1)])
    manifest.update(fields)
    atomic_json(folder/'manifest.json', manifest)
    return folder, manifest


class SlimPublicationTests(unittest.TestCase):
    def test_slim_file_is_uploaded_with_the_exports_headers_and_read_back_before_the_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, manifest = slim_bundle(tmp)
            s3 = Bucket()
            publish.publish_bundle(s3, 'b', folder, now=NOW)
            key = 'tiles/seafloor/regions/morro-bay/habitat-slim.geojson.gz'
            self.assertEqual(s3.objects[key], (folder/'habitat-slim.geojson.gz').read_bytes())
            self.assertEqual(s3.metadata[key]['CacheControl'], 'no-store')
            self.assertEqual(s3.metadata[key]['ContentType'], 'application/gzip')
            self.assertEqual(s3.metadata[key]['Metadata']['sha256'], manifest['slim_sha256'])
            export_key = 'tiles/seafloor/regions/morro-bay/habitat-export.geojson'
            self.assertEqual(s3.metadata[export_key]['CacheControl'], s3.metadata[key]['CacheControl'])
            self.assertIn(key, s3.gets)
            control = 'tiles/seafloor/manifest-morro-bay.json'
            self.assertLess(s3.puts.index(key), len(s3.puts) - 1 - s3.puts[::-1].index(control))
            self.assertEqual(json.loads(s3.objects[control])['slim_sha256'], manifest['slim_sha256'])

    def test_changed_or_unlisted_slim_file_never_uploads(self):
        for case in ('changed', 'name', 'unlisted-extra', 'hash-missing'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                folder, manifest = slim_bundle(tmp)
                if case == 'changed': (folder/'habitat-slim.geojson.gz').write_bytes(b'corrupt')
                if case == 'name': manifest['slim_file'] = '../habitat-slim.geojson.gz'
                if case == 'unlisted-extra': (folder/'other.geojson.gz').write_bytes(b'x')
                if case == 'hash-missing': del manifest['slim_sha256']
                atomic_json(folder/'manifest.json', manifest)
                s3 = Bucket()
                with self.assertRaises(ValueError):
                    publish.publish_bundle(s3, 'b', folder, now=NOW)
                self.assertEqual(s3.puts, [])

    def test_a_slim_file_the_manifest_does_not_name_is_an_unexpected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, manifest = bundle(tmp)
            (folder/'habitat-slim.geojson.gz').write_bytes(b'x')
            s3 = Bucket()
            with self.assertRaisesRegex(ValueError, 'Unexpected file'):
                publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(s3.puts, [])

    def test_corrupt_slim_readback_keeps_alias_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, _ = slim_bundle(tmp)
            s3 = Bucket()
            real = s3.get_object
            def corrupt(*, Bucket, Key):
                got = real(Bucket=Bucket, Key=Key)
                if Key.endswith('habitat-slim.geojson.gz'):
                    import io
                    got = {'Body': io.BytesIO(b'bad read-back')}
                return got
            s3.get_object = corrupt
            with self.assertRaisesRegex(ValueError, 'slim reef file read-back'):
                publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(json.loads(s3.objects['tiles/seafloor/manifest-morro-bay.json'])['status'], 'updating')


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
                        self.assertFalse((folder/'habitat-slim.geojson.gz').exists())
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

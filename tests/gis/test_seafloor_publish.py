"""Offline publication, private recovery and revision/expiry gate regressions."""
from datetime import timedelta
import gzip
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from skippercast import http
from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import publish, state_cache, jobs
from skippercast.seafloor.io import sha256
from skippercast.seafloor.verify import verify_public
from tests import http_fixture
from tests._support import NOW


class Missing(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class Bucket:
    exceptions = SimpleNamespace(NoSuchKey=Missing)

    def __init__(self):
        self.objects, self.puts, self.gets, self.metadata = {}, [], [], {}
        self.corrupt_alias = False

    def get_object(self, *, Bucket, Key):
        self.gets.append(Key)
        if Key not in self.objects:
            raise Missing()
        value = self.objects[Key]
        if self.corrupt_alias and Key == 'tiles/seafloor/seafloor-morro-bay.pmtiles':
            value = b'bad read-back'
        return {'Body': io.BytesIO(value)}

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise Missing()
        return {}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.puts.append(Key)
        self.objects[Key] = Body.read() if hasattr(Body, 'read') else Body
        self.metadata[Key] = kwargs

    def delete_objects(self, *, Bucket, Delete):
        for item in Delete['Objects']:
            self.objects.pop(item['Key'], None)


def bundle(root):
    folder = Path(root)/'bundle'
    folder.mkdir()
    archive = folder/'seafloor-morro-bay.pmtiles'
    archive.write_bytes(b'PMTiles\x03fixture')
    atomic_json(folder/'ledger.json', {'region': 'morro-bay'})
    atomic_json(folder/'habitat-export.geojson', {'region':'morro-bay', 'features':[]})
    manifest = {'region': 'morro-bay', 'status': 'ready',
        'expires_at': (NOW+timedelta(days=1)).isoformat(),
        'archive': archive.name, 'archive_sha256': sha256(archive),
        'archive_bytes': archive.stat().st_size, 'ledger_sha256': sha256(folder/'ledger.json'),
        'export_file':'habitat-export.geojson', 'export_sha256':sha256(folder/'habitat-export.geojson')}
    atomic_json(folder/'manifest.json', manifest)
    return folder, manifest


class PublicationTests(unittest.TestCase):
    def test_build_preserves_canonical_geometry_and_adds_an_interior_reference(self):
        from shapely.geometry import shape
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            geometry = {'type':'Polygon', 'coordinates':[
                [[-121,35],[-120.99,35],[-120.99,35.01],[-121,35.01],[-121,35]],
                [[-120.999,35.001],[-120.991,35.001],[-120.991,35.009],[-120.999,35.009],[-120.999,35.001]]]}
            properties = {'id':'test-reef', 'terrain':{'grade':'A','score':90}, 'fit':{'lingcod':3},
                          'source_ids':['native'], 'screen':{'status':'pass'}, 'depth_min_ft':90, 'depth_max_ft':120}
            layers = {'cells':[], 'habitat':[{'type':'Feature','geometry':geometry,
                       'properties':publish.flat_properties(properties)}]}
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reference':{}, 'reaches':[]})
            atomic_json(root/'catalog/surveys.json', {'surveys':[{'id':'native','url':'https://example.test/original'}]})
            def archive(tool, layers, path, **kwargs):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'PMTiles\x03fixture')
            with patch.object(publish,'region_layers',return_value=(layers,{},NOW+timedelta(days=1))), \
                 patch('scripts.build_map_tiles.build_vector_archive',side_effect=archive):
                folder, manifest = publish.build('morro-bay', root=root, tool='fixture', now=NOW)
            export = folder/manifest['export_file']
            self.assertEqual(export.name, 'habitat-export.geojson.gz')
            decoded = gzip.decompress(export.read_bytes())
            data = json.loads(decoded)
            f = data['features'][0]
            self.assertEqual(f['geometry'], geometry)
            self.assertEqual(f['properties']['terrain'], properties['terrain'])
            self.assertEqual(f['properties']['source_urls'], ['https://example.test/original'])
            w = f['properties']['waypoint']
            from shapely.geometry import Point
            self.assertTrue(shape(geometry).contains(Point(w['longitude'],w['latitude'])))
            self.assertNotIn('depth',w)
            self.assertEqual(manifest['export_sha256'], sha256(export))
            self.assertEqual(manifest['export_bytes'], export.stat().st_size)
            self.assertEqual(manifest['export_decoded_bytes'], len(decoded))
            self.assertFalse((folder/'habitat-export.geojson').exists())
            self.assertEqual(export.read_bytes(), gzip.compress(decoded, mtime=0))

    def test_publication_is_scoped_readback_precedes_ready_and_metadata_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, manifest = bundle(tmp)
            s3 = Bucket()
            other = 'tiles/seafloor/regions/other/retained.pmtiles'
            s3.objects[other] = b'keep'
            key = publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(s3.objects[other], b'keep')
            control = 'tiles/seafloor/manifest-morro-bay.json'
            self.assertEqual(s3.puts[-1], control)
            self.assertLess(s3.puts.index(control), s3.puts.index(key))
            self.assertIn(key, s3.gets)
            self.assertEqual(json.loads(s3.objects[control]), manifest)
            self.assertEqual(s3.metadata[key]['Metadata']['sha256'], manifest['archive_sha256'])
            self.assertTrue(all(k.startswith('tiles/seafloor/') for k in s3.puts))

    def test_corrupt_readback_keeps_alias_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, _ = bundle(tmp)
            s3 = Bucket()
            s3.corrupt_alias = True
            with self.assertRaisesRegex(ValueError, 'read-back'):
                publish.publish_bundle(s3, 'b', folder, now=NOW)
            self.assertEqual(json.loads(s3.objects['tiles/seafloor/manifest-morro-bay.json'])['status'], 'updating')

    def test_bad_bundle_and_expired_screen_never_upload(self):
        for case in ('extra', 'archive', 'ledger', 'export', 'expired', 'expires-now', 'path'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                folder, manifest = bundle(tmp)
                if case == 'extra': (folder/'source.bag').write_bytes(b'private')
                if case == 'archive': (folder/manifest['archive']).write_bytes(b'corrupt')
                if case == 'ledger': (folder/'ledger.json').write_text('{}')
                if case == 'export': (folder/'habitat-export.geojson').write_text('{}')
                if case == 'expired': manifest['expires_at'] = '2000-01-01T00:00:00+00:00'
                if case == 'expires-now': manifest['expires_at'] = NOW.isoformat()
                if case == 'path': manifest['archive'] = '../seafloor-morro-bay.pmtiles'
                atomic_json(folder/'manifest.json', manifest)
                s3 = Bucket()
                with self.assertRaises(ValueError): publish.publish_bundle(s3, 'b', folder, now=NOW)
                self.assertEqual(s3.puts, [])

    def test_missing_credentials_is_failure_and_branch_cannot_upload(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'credentials required'): publish.credentials()
        with patch.object(publish.subprocess, 'check_output', side_effect=['branch\n', 'main\n']):
            with self.assertRaisesRegex(ValueError, 'main commit'): publish.upload('morro-bay')
        with patch.object(publish.subprocess, 'check_output', side_effect=['same\n', 'same\n', 'src/changed.py\n']):
            with self.assertRaisesRegex(ValueError, 'differs from main'): publish.upload('morro-bay')

    def test_tile_properties_retain_unknowns_and_nested_provenance(self):
        p = {'terrain': {'grade': 'B', 'score': 2}, 'fit': {'lingcod': 3, 'shelf-rockfish': 'unknown'},
             'evidence': [{'family': 'same-survey'}], 'vertical_datum': 'unknown'}
        result = publish.flat_properties(p)
        self.assertEqual(json.loads(result['evidence']), p['evidence'])
        self.assertEqual(result['fit_shelf_rockfish'], 'unknown')
        self.assertEqual(result['vertical_datum'], 'unknown')
        self.assertEqual(result['terrain_grade'], 'B')

    def test_stale_receipt_or_held_feature_is_rejected_before_encoding(self):
        for case in ('stale', 'held', 'unqualified', 'corrupt', 'private'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ref = root/'var/seafloor/reference/cells.json'
                atomic_json(ref, {'cells': []})
                atomic_json(root/'dist/data/seafloor-ledger.json', {'reference_cells_sha256': sha256(ref),
                    'reaches': [{'id': 'r01', 'region': 'morro-bay', 'status': 'partial'}]})
                out = root/'var/seafloor/reaches/r01'
                p = {'tier': 1 if case == 'unqualified' else 2, 'status': 'habitat', 'exportable': True,
                     'screen': {'status': 'pass'}}
                atomic_json(out/'habitat.geojson', {'features': [{'properties': p}]})
                receipt = {'inputs': {'screen': 'old' if case == 'stale' else 'now'},
                           'outputs': {'habitat.geojson': 'bad' if case == 'corrupt' else sha256(out/'habitat.geojson')}}
                if case == 'private':
                    receipt['inputs']['sources'] = [{'status': 'physical-only'}]
                atomic_json(out/'run.json', receipt)
                with patch.object(publish, 'load_snapshot', return_value={'status': 'held' if case == 'held' else 'ready'}), \
                     patch.object(publish, 'input_identity', return_value='now'):
                    with self.assertRaises(ValueError): publish.region_layers(root, 'morro-bay', rerun=False)

    def test_coverage_checkpoint_cannot_republish_old_habitat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cell = {'id': '3310:0:0', 'reach': 'r01', 'tier': 1,
                    'source_id': 'native', 'band_area_m2': 62500}
            ref = root/'var/seafloor/reference/cells.json'
            atomic_json(ref, {'cells': [cell]})
            atomic_json(root/'catalog/surveys.json', {'surveys': []})
            atomic_json(root/'catalog/habitat-rules.json', {'rule_version': 'test'})
            atomic_json(root/'dist/data/seafloor-ledger.json', {
                'reference_cells_sha256': sha256(ref), 'reaches': [
                    {'id': 'r01', 'region': 'morro-bay', 'status': 'terrain-pending'}]})
            folder = root/'var/seafloor/reaches/r01'
            atomic_json(folder/'coverage-cells.json', {'cells': [cell]})
            atomic_json(folder/'habitat.geojson', {'features': [{'stale': 'must never publish'}]})
            atomic_json(folder/'coverage-checkpoint.json', {
                'catalog_sha256': sha256(root/'catalog/surveys.json'),
                'rules_sha256': sha256(root/'catalog/habitat-rules.json'),
                'reference_sha256': sha256(ref),
                'cells_sha256': sha256(folder/'coverage-cells.json')})
            with patch.object(publish, 'run') as rerun:
                layers, receipts, _ = publish.region_layers(root, 'morro-bay')
                self.assertEqual(layers['habitat'], [])
                self.assertEqual(layers['cells'][0]['properties']['tier'], 1)
                self.assertEqual(receipts, {})
                rerun.assert_not_called()
            atomic_json(root/'catalog/habitat-rules.json', {'rule_version': 'changed'})
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                publish.region_layers(root, 'morro-bay')

    def test_public_probe_rejects_an_old_backend_or_wrong_archive(self):
        manifest = {'region': 'morro-bay', 'status': 'ready', 'archive': 'seafloor-morro-bay.pmtiles',
                    'archive_sha256': 'a'*64, 'archive_bytes': 500}
        headers = {'Content-Range': 'bytes 0-126/500', 'X-Feed-Source': 'r2', 'Cache-Control': 'no-store'}
        for status, digest in ((200, 'a'*64), (206, 'b'*64), (206, 'a'*64)):
            session, script, _ = http_fixture.session(
                (200, json.dumps({**manifest, 'archive_sha256': digest}).encode()),
                (status, b'PMTiles\x03'+b'\0'*119, headers))
            if status == 206 and digest == 'a'*64:
                self.assertEqual(verify_public('morro-bay', manifest, session=session)['range_status'], 206)
                self.assertEqual(script.requests[1]['headers']['Range'], 'bytes=0-126')
            else:
                with self.assertRaises(ValueError): verify_public('morro-bay', manifest, session=session)
            self.assertEqual(script.requests[0]['headers']['User-Agent'], http.USER_AGENT)
            self.assertEqual(script.requests[0]['headers']['Cache-Control'], 'no-cache')
        # A backend that ignores Range sends the whole archive: over the probe's byte bound.
        session, _, _ = http_fixture.session((200, json.dumps(manifest).encode()),
                                             (206, b'PMTiles\x03'+b'\0'*500, headers))
        with self.assertRaises(ValueError): verify_public('morro-bay', manifest, session=session)

    def test_prepare_refresh_failure_holds_existing_public_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root/'var/seafloor/reference/cells.json'
            atomic_json(ref, {'cells': []})
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reference_cells_sha256': sha256(ref),
                'reaches': [{'id': 'r01', 'region': 'morro-bay', 'status': 'partial'}]})
            s3 = Bucket()
            with patch.object(jobs, 'credentials', return_value=(s3, 'b')), \
                 patch.object(state_cache, 'restore', return_value=False), \
                 patch.object(jobs, 'plan', return_value={'selected': [{'reach': 'r01', 'region': 'morro-bay'}]}), \
                 patch.object(jobs, 'report', return_value='fixture report'), \
                 patch.object(state_cache, 'save'), \
                 patch.object(jobs, 'refresh', side_effect=ValueError('publisher unavailable')):
                result = jobs.prepare(root, 'morro-bay')
                self.assertEqual(result['include'], [{'reach': 'r01', 'region': 'morro-bay'}])
                self.assertTrue((root/'var/seafloor/screen/refresh-failure.json').exists())
            self.assertEqual(json.loads(s3.objects['tiles/seafloor/manifest-morro-bay.json'])['status'], 'held')


class PrivateRecoveryTests(unittest.TestCase):
    def test_roundtrip_hashes_private_keys_no_repeat_download_and_scope_isolation(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            source = Path(first)/'var/seafloor/cache'/('a'*64)/'source.bag'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'original survey')
            s3 = Bucket()
            state_cache.save(s3, 'b', first, 'r01', [source])
            state_cache.save(s3, 'b', first, 'r02', [source])
            self.assertTrue(all(k.startswith('seafloor-cache/') for k in s3.puts))
            blob = f'seafloor-cache/{sha256(source)}/source.bag'
            self.assertEqual(s3.puts.count(blob), 1)
            self.assertTrue(state_cache.restore(s3, 'b', second, 'r01'))
            target = Path(second)/source.relative_to(first)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            s3.gets.clear()
            state_cache.restore(s3, 'b', second, 'r01')
            self.assertNotIn(blob, s3.gets)
            self.assertIn('seafloor-cache/state/r02.json', s3.objects)
            self.assertFalse(state_cache.restore(s3, 'b', second, 'absent'))

    def test_traversal_and_corrupt_bytes_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            s3 = Bucket()
            index = {'version': 1, 'scope': 'r01', 'files': [{'path': '../escaped', 'sha256': 'a'*64, 'bytes': 3}]}
            key = 'seafloor-cache/state/r01.json'
            s3.objects[key] = json.dumps(index).encode()
            with self.assertRaisesRegex(ValueError, 'restore path'): state_cache.restore(s3, 'b', tmp, 'r01')
            index['files'][0]['path'] = 'reaches/r01/cells.json'
            s3.objects[key] = json.dumps(index).encode()
            s3.objects[f"seafloor-cache/{'a'*64}/cells.json"] = b'bad'
            with self.assertRaisesRegex(ValueError, 'checksum'): state_cache.restore(s3, 'b', tmp, 'r01')
            self.assertFalse((Path(tmp)/'var/seafloor/reaches/r01/cells.json').exists())


if __name__ == '__main__':
    unittest.main()

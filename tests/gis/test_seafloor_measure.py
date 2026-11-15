"""F1C-MEASURE: the stage-only receipt run reads R2 and refuses every write."""
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scripts.publish_r2 as publish_r2
from skippercast.seafloor import fetch, measure, publish, state_cache


class Missing(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class Bucket:
    """Fake R2: every call is recorded; writes are recorded so the test can prove there were none."""
    exceptions = SimpleNamespace(NoSuchKey=Missing)

    def __init__(self, objects):
        self.objects, self.calls = dict(objects), []

    def get_object(self, Bucket, Key):
        self.calls.append(('get_object', Key))
        if Key not in self.objects:
            raise Missing(Key)
        return {'Body': io.BytesIO(self.objects[Key]), 'ETag': '"e"'}

    def head_object(self, Bucket, Key):
        self.calls.append(('head_object', Key))
        return {}

    def list_objects_v2(self, Bucket, Prefix, **kwargs):
        self.calls.append(('list_objects_v2', Prefix))
        return {'IsTruncated': False, 'Contents': [{'Key': k, 'ETag': '"e"', 'Size': len(v), 'LastModified': 't'}
                                                    for k, v in sorted(self.objects.items()) if k.startswith(Prefix)]}

    def put_object(self, **kwargs):
        self.calls.append(('put_object', kwargs.get('Key')))

    def delete_object(self, **kwargs):
        self.calls.append(('delete_object', kwargs.get('Key')))


class StageOnlyMeasureTest(unittest.TestCase):
    def test_receipt_run_reads_only_and_refuses_every_live_write(self):
        region = 'morro-bay'
        inventory = lambda name: json.dumps({'version': 1, 'scope': name, 'files': []}).encode()
        bucket = Bucket({f'tiles/seafloor/manifest-{region}.json': json.dumps({'status': 'ready', 'reach_inputs': {}}).encode(),
                         f'tiles/seafloor/seafloor-{region}.pmtiles': b'C',
                         'seafloor-cache/state/shared.json': inventory('shared'),
                         'seafloor-cache/state/morro-bay-r01.json': inventory('morro-bay-r01')})
        empty = gzip.compress(b'', mtime=0)
        control8, rough8 = gzip.compress(bytes(9000), mtime=0), gzip.compress(bytes(10), mtime=0)
        tiles = {b'C': {(8, 42, 101): control8, (12, 672, 1618): empty},
                 b'RK': {(8, 42, 101): control8, (12, 672, 1618): empty},
                 b'RC': {(8, 42, 101): rough8, (12, 672, 1618): empty}}
        refused = []

        def fake_build(name, *, root, tool):
            # Every publication path is refused while the switch is on, before any S3 call.
            for attempt in (lambda: publish.publish_bundle(None, None, None), lambda: publish.upload(name),
                            lambda: state_cache.save(None, None, root, name, []),
                            lambda: fetch.upload_private(None, None, root),
                            lambda: publish_r2.sync(None, None, root, 'x'),
                            lambda: publish.credentials()[0].put_object(Key='tiles/seafloor/x'),
                            lambda: publish.credentials()[0].delete_object(Key='x'),
                            lambda: publish.credentials()[0].copy_object(Key='x')):
                with self.assertRaises(measure.StageOnlyWrite):
                    attempt()
                refused.append(True)
            folder = Path(root)/'var/seafloor/public'/name
            folder.mkdir(parents=True, exist_ok=True)
            from scripts import build_map_tiles
            rough = getattr(build_map_tiles.build_vector_archive, 'keywords', {}).get('coarse_first')
            (folder/f'seafloor-{name}.pmtiles').write_bytes(b'RC' if rough else b'RK')
            return folder, {'layers': {'habitat': 1}, 'reach_inputs': {}}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict('os.environ', {'SEAFLOOR_STAGE_ONLY': '1', 'GITHUB_REF': 'refs/heads/rb/f1c-measure',
                                          'CLOUDFLARE_API_TOKEN': 'test-token', 'CLOUDFLARE_ACCOUNT_ID': 'test'}), \
                patch.object(publish_r2, 'client', lambda token, account: bucket), \
                patch.object(publish_r2, 'sync', publish_r2.sync), \
                patch.object(publish, 'publish_bundle', publish.publish_bundle), \
                patch.object(publish, 'upload', publish.upload), \
                patch.object(state_cache, 'save', state_cache.save), \
                patch.object(state_cache, 'upload_private', state_cache.upload_private), \
                patch.object(fetch, 'upload_private', fetch.upload_private), \
                patch.object(publish, 'build', fake_build), \
                patch.object(measure, 'read_tiles', lambda data: tiles[data]):
            root = Path(tmp)
            (root/'dist/data').mkdir(parents=True)
            (root/'dist/data/seafloor-ledger.json').write_text(json.dumps({'reaches': [
                {'id': 'morro-bay-r01', 'region': region, 'status': 'habitat-screened'},
                {'id': 'other-r01', 'region': 'other', 'status': 'habitat-screened'}]}))
            receipt = measure.measure(root, root/'receipt.json', region=region, tool=sys.executable)
            written = json.loads((root/'receipt.json').read_text())
            with patch.dict('os.environ', {'SEAFLOOR_STAGE_ONLY': ''}), self.assertRaises(measure.StageOnlyWrite):
                measure.require_stage_only()
            with patch.dict('os.environ', {'GITHUB_REF': 'refs/heads/main'}), self.assertRaises(measure.StageOnlyWrite):
                measure.require_stage_only()

        self.assertEqual(len(refused), 16)  # two builds, eight refused write paths each
        self.assertNotIn('error', receipt)
        self.assertEqual({call for call, _ in bucket.calls}, {'get_object', 'head_object', 'list_objects_v2'})
        self.assertNotIn('seafloor-cache/state/other-r01.json', [key for _, key in bucket.calls])
        self.assertTrue(written['bucket_unchanged'])
        self.assertEqual(written['per_zoom']['8']['Rc_candidate']['bytes'], len(rough8))
        self.assertEqual(written['per_zoom']['8']['Rc_vs_A1_percent'], round((len(rough8) - 464493) / 464493 * 100, 3))
        self.assertTrue(written['acceptance']['item0_calibration_Rk_vs_C']['pass'])
        self.assertTrue(written['acceptance']['item3_detail_Rc_vs_Rk_z12_15']['pass'])
        self.assertFalse(written['size_pass'])  # z9-z11 tiles absent: an empty rough zoom is an anomaly, never a pass
        self.assertFalse(written['pass'])
        # The switch did not leak: the real helpers are back after the run.
        self.assertFalse(getattr(publish_r2.client, 'stage_only', False))


if __name__ == '__main__':
    unittest.main()

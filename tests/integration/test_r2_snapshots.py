"""Coherent publication under upload failure, races, lost acknowledgments and rollback."""
from io import BytesIO
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from scripts.publish_r2 import CURRENT, sync


class Missing(Exception):
    pass


class FakeS3:
    class exceptions:
        NoSuchKey = Missing

    def __init__(self):
        self.objects = {}
        self.lock = threading.RLock()
        self.fail = None
        self.corrupt = None
        self.transform = None
        self.before_commit = None
        self.lost_ack = False
        self.deletes = 0

    def get_object(self, Bucket, Key):
        with self.lock:
            if Key not in self.objects:
                raise Missing(Key)
            row = self.objects[Key]
            return {**row, 'Body': BytesIO(row['Body'])}

    def head_object(self, Bucket, Key):
        return {k: v for k, v in self.get_object(Bucket, Key).items() if k != 'Body'}

    def put_object(self, Bucket, Key, Body, **kwargs):
        if self.fail and self.fail(Key):
            raise OSError('injected upload failure')
        if Key.endswith(CURRENT) and self.before_commit:
            self.before_commit()
        with self.lock:
            current = self.objects.get(Key)
            if 'IfMatch' in kwargs and (not current or current['ETag'] != kwargs['IfMatch']):
                raise RuntimeError('PreconditionFailed')
            if kwargs.get('IfNoneMatch') == '*' and current:
                raise RuntimeError('PreconditionFailed')
            data = bytes(Body)
            stored = b'corrupt' if self.corrupt and self.corrupt(Key) else data
            if self.transform:
                stored = self.transform(Key, stored)
            self.objects[Key] = {**kwargs, 'Body': stored, 'ETag': '"' + hashlib.sha256(stored).hexdigest() + '"',
                                 'ContentLength': len(stored)}
            if Key.endswith(CURRENT) and self.lost_ack:
                raise OSError('lost pointer acknowledgment')

    def delete_objects(self, **kwargs):
        self.deletes += 1
        raise AssertionError('snapshots must preserve historical data')


def published(s3, generation=None):
    if generation is None:
        generation = json.loads(s3.objects['forecasts/' + CURRENT]['Body'])['generation']
    manifest = json.loads(s3.objects[f'forecasts/.r2-releases/{generation}.json']['Body'])
    return {key: s3.objects[f'forecasts/.r2-objects/{sha}']['Body'] for key, sha in manifest['files'].items()}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s3 = FakeS3()
        self.write(self.root, 'old')
        # Legacy deployment stays available throughout first migration.
        self.s3.objects['forecasts/model/tiles/x.json'] = {'Body': b'legacy'}
        sync(self.s3, 'bucket', self.root, 'forecasts')
        self.old_pointer = self.s3.objects['forecasts/' + CURRENT].copy()
        self.old_generation = json.loads(self.old_pointer['Body'])['generation']

    def write(self, root, cycle):
        (root / 'model/tiles').mkdir(parents=True, exist_ok=True)
        (root / 'model/manifest.json').write_text(json.dumps({'cycle': cycle, 'tiles': ['x']}))
        (root / 'model/tiles/x.json').write_text(json.dumps({'cycle': cycle, 'values': [cycle]}))

    def assert_cycle(self, cycle, generation=None):
        rows = published(self.s3, generation)
        self.assertEqual(json.loads(rows['model/manifest.json'])['cycle'], cycle)
        self.assertEqual(json.loads(rows['model/tiles/x.json'])['cycle'], cycle)

    def test_failures_at_each_phase_never_mix_old_manifest_and_new_tile(self):
        for phase in ('.r2-objects/', '.r2-releases/', CURRENT):
            with self.subTest(phase=phase):
                self.write(self.root, 'new')
                self.s3.fail = lambda key: phase in key
                with self.assertRaises(OSError):
                    sync(self.s3, 'bucket', self.root, 'forecasts')
                self.assert_cycle('old')
                self.assertEqual(self.s3.objects['forecasts/' + CURRENT]['Body'], self.old_pointer['Body'])
                self.assertEqual(self.s3.objects['forecasts/model/tiles/x.json']['Body'], b'legacy')
        self.s3.fail = None
        sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assert_cycle('new')
        self.assert_cycle('old', self.old_generation)
        self.assertEqual(self.s3.deletes, 0)

    def test_corrupt_readback_cannot_commit_and_retry_refuses_poisoned_immutable_key(self):
        self.write(self.root, 'new')
        self.s3.corrupt = lambda key: '.r2-objects/' in key
        with self.assertRaisesRegex(RuntimeError, 'read-back hash mismatch'):
            sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assert_cycle('old')
        self.s3.corrupt = None
        with self.assertRaisesRegex(RuntimeError, 'read-back hash mismatch'):
            sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assert_cycle('old')

    def test_same_length_poisoned_tile_cannot_be_committed_on_retry(self):
        self.write(self.root, 'new')
        tile_sha = hashlib.sha256((self.root / 'model/tiles/x.json').read_bytes()).hexdigest()
        self.s3.transform = lambda key, data: data.replace(b'new', b'bad') if key.endswith(tile_sha) else data
        with self.assertRaisesRegex(RuntimeError, 'read-back hash mismatch'):
            sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assert_cycle('old')
        self.s3.transform = None
        # Metadata, ContentLength and key still describe the intended new bytes.
        with self.assertRaisesRegex(RuntimeError, 'read-back hash mismatch'):
            sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assertEqual(self.s3.objects['forecasts/' + CURRENT]['Body'], self.old_pointer['Body'])
        self.assert_cycle('old')

    def test_noop_republication_also_verifies_existing_bytes(self):
        key = 'forecasts/.r2-objects/' + hashlib.sha256((self.root / 'model/tiles/x.json').read_bytes()).hexdigest()
        self.s3.objects[key]['Body'] = self.s3.objects[key]['Body'].replace(b'old', b'bad')
        with self.assertRaisesRegex(RuntimeError, 'read-back hash mismatch'):
            sync(self.s3, 'bucket', self.root, 'forecasts')

    def test_snapshot_readback_mismatch_preserves_current(self):
        self.write(self.root, 'new')
        self.s3.corrupt = lambda key: '.r2-releases/' in key
        with self.assertRaisesRegex(RuntimeError, 'snapshot read-back mismatch'):
            sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assert_cycle('old')

    def test_concurrent_publishers_cas_one_complete_winner(self):
        second = self.root / 'second'
        self.write(self.root, 'new-a')
        self.write(second, 'new-b')
        # Do not nest the second source inside the first published directory.
        first = self.root / 'first'
        self.write(first, 'new-a')
        barrier = threading.Barrier(2)
        self.s3.before_commit = lambda: barrier.wait(timeout=5)
        def publish(root):
            try:
                sync(self.s3, 'bucket', root, 'forecasts')
                return 'success'
            except RuntimeError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(publish, [first, second]))
        self.assertCountEqual(result, ['success', 'PreconditionFailed'])
        rows = published(self.s3)
        cycle = json.loads(rows['model/manifest.json'])['cycle']
        self.assertIn(cycle, ['new-a', 'new-b'])
        self.assert_cycle(cycle)
        self.assert_cycle('old', self.old_generation)

    def test_lost_final_ack_leaves_complete_new_release_and_retry_is_noop(self):
        self.write(self.root, 'new')
        self.s3.lost_ack = True
        with self.assertRaises(OSError):
            sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assert_cycle('new')
        self.s3.lost_ack = False
        self.assertIn('unchanged', sync(self.s3, 'bucket', self.root, 'forecasts'))
        self.assert_cycle('new')

    def test_republishing_old_source_is_coherent_rollback_and_preserves_new_reader(self):
        self.write(self.root, 'new')
        sync(self.s3, 'bucket', self.root, 'forecasts')
        new_generation = json.loads(self.s3.objects['forecasts/' + CURRENT]['Body'])['generation']
        self.write(self.root, 'old')
        sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assert_cycle('old')
        self.assert_cycle('new', new_generation)
        self.assertEqual(self.s3.deletes, 0)

    def test_removed_path_does_not_reappear_from_legacy_and_bytes_remain_for_old_reader(self):
        (self.root / 'model/tiles/x.json').unlink()
        sync(self.s3, 'bucket', self.root, 'forecasts')
        self.assertNotIn('model/tiles/x.json', published(self.s3))
        self.assertIn('model/tiles/x.json', published(self.s3, self.old_generation))

    def test_empty_source_and_reserved_paths_cannot_erase_previous_release(self):
        empty = self.root / 'empty'; empty.mkdir()
        with self.assertRaises(ValueError):
            sync(self.s3, 'bucket', empty, 'forecasts')
        (empty / '.r2-current.json').write_text('{}')
        with self.assertRaises(ValueError):
            sync(self.s3, 'bucket', empty, 'forecasts')
        self.assert_cycle('old')


@unittest.skipUnless(importlib.util.find_spec('boto3') and importlib.util.find_spec('moto'), 'moto/boto3 not installed')
class SDKCompatibilityTests(unittest.TestCase):
    def test_actual_sdk_metadata_streaming_and_conditional_put_migrate_and_rollback(self):
        import boto3
        from botocore.exceptions import ClientError
        from moto import mock_aws
        with mock_aws(), tempfile.TemporaryDirectory() as directory:
            s3 = boto3.client('s3', region_name='us-east-1', aws_access_key_id='test', aws_secret_access_key='test')
            s3.create_bucket(Bucket='feeds')
            root = Path(directory)
            (root / 'latest.json').write_text('{"cycle":"old"}')
            for prefix in ('conditions', 'data', 'forecasts'):
                with self.subTest(prefix=prefix):
                    key = prefix + '/' + CURRENT
                    sync(s3, 'feeds', root, prefix)
                    old = s3.get_object(Bucket='feeds', Key=key)
                    old_pointer = old['Body'].read()
                    (root / 'latest.json').write_text('{"cycle":"new"}')
                    sync(s3, 'feeds', root, prefix)
                    with self.assertRaises(ClientError) as error:
                        s3.put_object(Bucket='feeds', Key=key, Body=old_pointer, IfMatch=old['ETag'])
                    self.assertEqual(error.exception.response['ResponseMetadata']['HTTPStatusCode'], 412)
                    (root / 'latest.json').write_text('{"cycle":"old"}')
                    sync(s3, 'feeds', root, prefix)
                    self.assertEqual(s3.get_object(Bucket='feeds', Key=key)['Body'].read(), old_pointer)

"""Offline coverage of quiet deletes in the legacy tile mirror."""
import hashlib
import io
import json

import pytest

from scripts.publish_r2 import INDEX, sync


BUCKET = 'fixture-bucket'
INDEX_KEY = f'tiles/{INDEX}'


class QuietStore:
    def __init__(self, local_index, stale_keys, denied=()):
        old_index = {**local_index, **{key: 'old' for key in stale_keys}}
        self.objects = {f'tiles/{key}': b'old tile' for key in stale_keys}
        self.objects[INDEX_KEY] = json.dumps(old_index).encode()
        self.denied = set(denied)
        self.index_writes = []

    def get_object(self, *, Bucket, Key):
        assert Bucket == BUCKET
        return {'Body': io.BytesIO(self.objects[Key])}

    def delete_objects(self, *, Bucket, Delete):
        assert Bucket == BUCKET
        assert Delete['Quiet'] is True
        assert len(Delete['Objects']) <= 1000  # S3 DeleteObjects API limit.
        errors = []
        for entry in Delete['Objects']:
            key = entry['Key']
            if key in self.denied:
                errors.append({'Key': key, 'Code': 'AccessDenied'})
            else:
                # S3 treats missing keys as successful deletes and omits them in quiet mode.
                self.objects.pop(key, None)
        return {'Errors': errors} if errors else {}

    def put_object(self, *, Bucket, Key, Body, ContentType):
        assert (Bucket, Key, ContentType) == (BUCKET, INDEX_KEY, 'application/json')
        self.index_writes.append(Body)
        self.objects[Key] = Body


@pytest.fixture
def local_index(tmp_path):
    body = b'kept tile'
    (tmp_path / 'kept.png').write_bytes(body)
    return {'kept.png': hashlib.sha256(body).hexdigest()}


def test_partial_delete_preserves_old_index_until_retry(tmp_path, local_index):
    # Ignoring quiet-mode Errors would drop the only record of the denied tiles.
    stale = [f'old/{i:04}.png' for i in range(1001)]
    denied = {'tiles/old/0000.png', 'tiles/old/1000.png'}
    store = QuietStore(local_index, stale, denied)
    old_index = store.objects[INDEX_KEY]

    with pytest.raises(RuntimeError, match=r'failed to delete 2 stale keys'):
        sync(store, BUCKET, tmp_path, 'tiles')
    assert store.index_writes == []
    assert store.objects[INDEX_KEY] == old_index
    assert set(store.objects) == {INDEX_KEY, *denied}

    store.denied.clear()
    assert sync(store, BUCKET, tmp_path, 'tiles') == (
        'R2 fixture-bucket/tiles: 0 uploaded (0 pointers last), 1001 removed, 1 unchanged.'
    )
    assert store.objects == {INDEX_KEY: json.dumps(local_index).encode()}
    assert store.index_writes == [store.objects[INDEX_KEY]]


def test_clean_quiet_delete_without_deleted_entries_commits_index(tmp_path, local_index):
    # A quiet success has no Deleted list to count; the prior summary and index still apply.
    store = QuietStore(local_index, ['old.png'])

    assert sync(store, BUCKET, tmp_path, 'tiles') == (
        'R2 fixture-bucket/tiles: 0 uploaded (0 pointers last), 1 removed, 1 unchanged.'
    )
    assert store.objects == {INDEX_KEY: json.dumps(local_index).encode()}
    assert store.index_writes == [store.objects[INDEX_KEY]]

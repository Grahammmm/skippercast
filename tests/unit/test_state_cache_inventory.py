"""RF0510-4: a damaged private state inventory is one named ValueError before any side effect."""
import hashlib
import io
import json

import pytest

from skippercast.seafloor import state_cache

DIGEST = 'a' * 64


class Missing(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class FakeS3:
    def __init__(self, body=None):
        self.body = body

    def get_object(self, Bucket, Key):
        assert Key.startswith('seafloor-cache/state/')
        if self.body is None:
            raise Missing()
        return {'Body': io.BytesIO(self.body)}


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(state_cache, 'restore_private', lambda *a: recorded.append(a))
    return recorded


@pytest.fixture
def marker(tmp_path):
    path = tmp_path/'var/seafloor/screen/refresh-failure.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"failed": true}')
    return path


def inventory(files, scope='shared', version=1):
    return json.dumps({'version': version, 'scope': scope, 'files': files}).encode()


def restore(tmp_path, body, name='shared'):
    return state_cache.restore(FakeS3(body), 'bucket', tmp_path, name)


@pytest.mark.parametrize('body', [b'not json', b'[]', b'"text"', b'7', b'null', b'\xff'])
def test_unparseable_or_non_object_inventory_is_named(tmp_path, calls, marker, body):
    with pytest.raises(ValueError, match='^Invalid private state inventory$'):
        restore(tmp_path, body)
    assert calls == [] and marker.exists()


@pytest.mark.parametrize('body', [
    b'{"version": 1}',  # no scope
    b'{"scope": "shared"}',  # no version
    inventory([], version=True),
    inventory([], version='1'),
    inventory([], version=1.0),
    inventory([], version=2),
    inventory([], scope='other'),
])
def test_scope_or_version_mismatch_is_named(tmp_path, calls, marker, body):
    with pytest.raises(ValueError, match='^Private state scope mismatch$'):
        restore(tmp_path, body)
    assert calls == [] and marker.exists()


@pytest.mark.parametrize('size', ['missing', '12', True, False, -1, 12.0, None])
def test_entry_bytes_must_be_whole_non_negative_int(tmp_path, calls, marker, size):
    entry = {'path': 'reference/cells.json', 'sha256': DIGEST}
    if size != 'missing':
        entry['bytes'] = size
    good = {'path': 'reference/run.json', 'sha256': DIGEST, 'bytes': 3}
    with pytest.raises(ValueError, match='^Invalid private restore entry$'):
        restore(tmp_path, inventory([good, entry]))
    # Preflight runs over the whole batch: the earlier good entry is not fetched
    # and the shared refresh-failure marker survives.
    assert calls == [] and marker.exists()


def test_zero_bytes_entry_is_accepted(tmp_path, calls):
    path = tmp_path/'var/seafloor/reference/cells.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'')
    entry = {'path': 'reference/cells.json', 'sha256': hashlib.sha256(b'').hexdigest(), 'bytes': 0}
    assert restore(tmp_path, inventory([entry])) is True
    assert calls == []


def test_good_inventory_with_matching_file_restores_without_transfer(tmp_path, calls, marker):
    path = tmp_path/'var/seafloor/reference/cells.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{}')
    entry = {'path': 'reference/cells.json', 'sha256': hashlib.sha256(b'{}').hexdigest(), 'bytes': 2}
    assert restore(tmp_path, inventory([entry])) is True
    assert calls == []
    # Unchanged: a good shared inventory without the marker clears the stale marker.
    assert not marker.exists()


def test_good_inventory_transfers_a_missing_file(tmp_path, monkeypatch):
    recorded = []

    def fake_restore(s3, bucket, path, digest):
        recorded.append((path.relative_to(tmp_path).as_posix(), digest))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'abc')

    monkeypatch.setattr(state_cache, 'restore_private', fake_restore)
    entry = {'path': 'reference/run.json', 'sha256': DIGEST, 'bytes': 3}
    assert restore(tmp_path, inventory([entry])) is True
    assert recorded == [('var/seafloor/reference/run.json', DIGEST)]


def test_missing_inventory_is_false(tmp_path, calls, marker):
    assert restore(tmp_path, None) is False
    assert calls == [] and marker.exists()


def test_oversized_inventory_is_named(tmp_path, calls, marker):
    with pytest.raises(ValueError, match='^Oversized state inventory$'):
        restore(tmp_path, b' ' * 5_000_001)
    assert calls == [] and marker.exists()

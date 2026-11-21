"""F11-10 / SCA-287: a restored object's declared size is checked before it is installed or reused.

Contract: an inventory entry whose size disagrees with its (valid-hash) object is rejected the
same way on a cold restore and a warm hit, and never replaces the previous local file. The
believable bug is the old order: stage, hash, rename, and only then compare the size.
"""
import hashlib
import io
import json

import pytest

from skippercast.seafloor import state_cache
from skippercast.seafloor.fetch import restore_private

BODY = b'x'  # one byte; the synthetic negative control declares two
DIGEST = hashlib.sha256(BODY).hexdigest()
RELATIVE = 'reference/run.json'


class FakeS3:
    """Serves the state inventory and one object; counts object fetches."""

    def __init__(self, declared):
        entry = {'path': RELATIVE, 'sha256': DIGEST, 'bytes': declared}
        self.inventory = json.dumps({'version': 1, 'scope': 'shared', 'files': [entry]}).encode()
        self.object_fetches = 0

    def get_object(self, Bucket, Key):
        if Key.startswith('seafloor-cache/state/'):
            return {'Body': io.BytesIO(self.inventory)}
        assert Key == f'seafloor-cache/{DIGEST}/run.json'
        self.object_fetches += 1
        return {'Body': io.BytesIO(BODY)}


def target(tmp_path):
    return tmp_path/'var/seafloor'/RELATIVE


def restore(tmp_path, declared):
    s3 = FakeS3(declared)
    return s3, state_cache.restore(s3, 'bucket', tmp_path, 'shared')


def test_cold_restore_rejects_wrong_size_before_install(tmp_path):
    path = target(tmp_path)
    with pytest.raises(ValueError, match='^Private restore size mismatch$'):
        restore(tmp_path, 2)
    assert not path.exists() and not list(path.parent.glob('*.part'))


def test_cold_restore_keeps_previous_local_file(tmp_path):
    path = target(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'previous')
    with pytest.raises(ValueError, match='^Private restore size mismatch$'):
        restore(tmp_path, 2)
    assert path.read_bytes() == b'previous' and not list(path.parent.glob('*.part'))


def test_warm_hit_rejects_the_same_wrong_size_and_keeps_file(tmp_path):
    path = target(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(BODY)  # hash-valid local copy
    s3 = FakeS3(2)
    with pytest.raises(ValueError, match='^Private restore size mismatch$'):
        state_cache.restore(s3, 'bucket', tmp_path, 'shared')
    assert path.read_bytes() == BODY and s3.object_fetches == 0


def test_corrected_inventory_passes_cold_and_warm(tmp_path):
    path = target(tmp_path)
    s3, restored = restore(tmp_path, 1)  # cold
    assert restored is True and path.read_bytes() == BODY and s3.object_fetches == 1
    s3, restored = restore(tmp_path, 1)  # warm: reused without a transfer
    assert restored is True and s3.object_fetches == 0


def test_restore_private_size_is_checked_before_rename(tmp_path):
    destination = tmp_path/'run.json'
    destination.write_bytes(b'previous')
    s3 = FakeS3(2)
    with pytest.raises(ValueError, match='size mismatch'):
        restore_private(s3, 'bucket', destination, DIGEST, size=2)
    assert destination.read_bytes() == b'previous' and not destination.with_suffix('.json.part').exists()
    restore_private(s3, 'bucket', destination, DIGEST, size=1)
    assert destination.read_bytes() == BODY

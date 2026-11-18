"""SCA-049: shared restore commits the screen hold state last."""
import hashlib
import io
import json
from pathlib import Path

import pytest

from skippercast.seafloor.state_cache import restore

MARKER = 'screen/refresh-failure.json'
LOCAL_HOLD = b'{"error":"local failure"}'
REMOTE_HOLD = b'{"error":"remote failure"}'
PAYLOADS = {
    'screen/snapshot.json': b'{"fixture":"snapshot"}',
    'screen/source-receipts.json': b'{"fixture":"receipts"}',
}


class MemoryS3:
    def __init__(self, payloads, marker, *, unavailable=None, bad_size=None):
        self.objects = {}
        self.observed = []
        self.marker = marker
        self.unavailable = unavailable
        files = []
        for path, body in payloads.items():
            digest = hashlib.sha256(body).hexdigest()
            self.objects[f'seafloor-cache/{digest}/{Path(path).name}'] = path, body
            files.append({'path': path, 'sha256': digest, 'bytes': len(body) + (path == bad_size)})
        self.inventory = json.dumps({'version': 1, 'scope': 'shared', 'files': files}).encode()

    def get_object(self, Bucket, Key):
        assert Bucket == 'synthetic'
        if Key == 'seafloor-cache/state/shared.json':
            return {'Body': io.BytesIO(self.inventory)}
        path, body = self.objects[Key]
        self.observed.append((path, self.marker.read_bytes() if self.marker.exists() else None))
        if path == self.unavailable:
            raise OSError('synthetic transfer failure')
        return {'Body': io.BytesIO(body)}


@pytest.fixture
def marker(tmp_path):
    marker = tmp_path / 'var/seafloor' / MARKER
    marker.parent.mkdir(parents=True)
    marker.write_bytes(LOCAL_HOLD)
    return marker


@pytest.mark.parametrize('failed_path', PAYLOADS, ids=['first-payload', 'final-payload'])
def test_shared_transfer_failure_preserves_local_hold(tmp_path, marker, failed_path):
    s3 = MemoryS3(PAYLOADS, marker, unavailable=failed_path)
    with pytest.raises(OSError, match='synthetic transfer failure'):
        restore(s3, 'synthetic', tmp_path, 'shared')

    assert marker.read_bytes() == LOCAL_HOLD
    assert s3.observed[-1] == (failed_path, LOCAL_HOLD)


def test_shared_final_payload_size_failure_preserves_local_hold(tmp_path, marker):
    s3 = MemoryS3(PAYLOADS, marker, bad_size='screen/source-receipts.json')
    with pytest.raises(ValueError, match='Private restore size mismatch'):
        restore(s3, 'synthetic', tmp_path, 'shared')

    assert marker.read_bytes() == LOCAL_HOLD


@pytest.mark.parametrize('remote_holds', [False, True], ids=['healthy', 'marker-bearing'])
def test_successful_shared_restore_applies_remote_hold_last(tmp_path, marker, remote_holds):
    # Put the remote marker first to make sure inventory order cannot apply it early.
    payloads = {MARKER: REMOTE_HOLD, **PAYLOADS} if remote_holds else PAYLOADS
    s3 = MemoryS3(payloads, marker)

    assert restore(s3, 'synthetic', tmp_path, 'shared') is True

    expected_order = [*PAYLOADS, MARKER] if remote_holds else list(PAYLOADS)
    assert s3.observed == [(path, LOCAL_HOLD) for path in expected_order]
    for path, body in payloads.items():
        assert (tmp_path / 'var/seafloor' / path).read_bytes() == body
    if not remote_holds:
        assert not marker.exists()

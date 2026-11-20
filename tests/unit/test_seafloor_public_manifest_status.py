"""The public probe requires a complete manifest before checking the archive."""
import json

import pytest

from skippercast.seafloor.verify import verify_public
from tests import http_fixture


@pytest.mark.parametrize('manifest_status', [206, 200])
def test_public_probe_requires_http_200_manifest(manifest_status):
    # A partial response can still contain parseable JSON that matches R2 exactly.
    manifest = {
        'region': 'morro-bay',
        'status': 'ready',
        'archive': 'seafloor-morro-bay.pmtiles',
        'archive_sha256': 'a' * 64,
        'archive_bytes': 500,
    }
    session, script, _ = http_fixture.session(
        (manifest_status, json.dumps(manifest).encode()),
        (206, b'PMTiles\x03' + b'\0' * 119, {
            'Content-Range': 'bytes 0-126/500',
            'X-Feed-Source': 'r2',
            'Cache-Control': 'no-store',
        }),
    )

    if manifest_status == 206:
        with pytest.raises(ValueError, match='Public manifest must return HTTP 200'):
            verify_public('morro-bay', manifest, session=session)
        assert len(script.requests) == 1
    else:
        assert verify_public('morro-bay', manifest, session=session) == {
            'region': 'morro-bay',
            'url': 'https://skippercast.com/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles',
            'archive_sha256': 'a' * 64,
            'range_status': 206,
        }
        assert len(script.requests) == 2

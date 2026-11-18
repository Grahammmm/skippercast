"""F11-05: an unlisted region's control archive must be structurally readable before anything is published.

Contract: ``control_receipt`` (the ordinary, no-reference branch) passes only a readable PMTiles v3 archive.
Believable bug: only the eight magic bytes were trusted, so ``b'PMTiles\\x03' + junk`` recorded
``unreadable`` yet ``pass=True`` and the build went on to publish an unusable map.
"""
import gzip
import zlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from skippercast.seafloor import rough_first
from tests.unit.test_rough_first_tile_spans import archive

MAGIC_ONLY = b'PMTiles\x03' + bytes(200)  # right prefix, zeroed header: compression byte is not gzip


def test_valid_ordinary_archive_passes_without_a_reference():
    receipt = rough_first.control_receipt('synthetic-region', archive())
    assert (receipt['mode'], receipt['gate'], receipt['pass'], receipt['failed']) == ('control', None, True, [])
    assert 'unreadable' not in receipt['archive']
    assert receipt['archive']['per_zoom'] == {'12': {'tiles': 1, 'bytes': 4}}
    assert 'FAIL' not in rough_first.summary(receipt)


def test_magic_prefixed_invalid_header_fails():
    receipt = rough_first.control_receipt('synthetic-region', MAGIC_ONLY)
    assert receipt['pass'] is False
    assert receipt['failed'] == ['unreadable archive']
    assert receipt['archive']['unreadable'] == 'ValueError'
    assert 'FAIL, nothing published' in rough_first.summary(receipt)


def test_corrupt_directory_stream_fails_not_raises():
    good = archive()
    root_length = int.from_bytes(good[16:24], 'little')
    # Same header and span, but the directory bytes are not valid gzip/deflate data.
    corrupt = good[:127] + bytes([0x1f, 0x8b, 8, 0]) + b'\xff' * (root_length - 4) + good[127 + root_length:]
    with pytest.raises((OSError, zlib.error)):
        gzip.decompress(corrupt[127:127 + root_length])
    receipt = rough_first.control_receipt('synthetic-region', corrupt)
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']


@pytest.mark.gis
def test_publish_refuses_unreadable_control_archive_and_keeps_prior_release(tmp_path):
    from skippercast.seafloor import publish

    folder = tmp_path/'var/seafloor/public/synthetic-region'
    folder.mkdir(parents=True)
    prior = folder/'manifest.json'
    prior.write_bytes(b'{"prior": "release"}')

    def build_archive(tool, layers, path, **kwargs):
        path.write_bytes(MAGIC_ONLY)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch.object(publish, 'region_layers', return_value=({'cells': [], 'habitat': []}, {}, now + timedelta(days=1))), \
            patch('scripts.build_map_tiles.build_vector_archive', side_effect=build_archive):
        with pytest.raises(rough_first.GateFailure, match='Unreadable seafloor archive'):
            publish.build('synthetic-region', root=tmp_path, tool='fixture', now=now)

    assert not (folder/'seafloor-synthetic-region.pmtiles').exists()
    assert prior.read_bytes() == b'{"prior": "release"}'
    assert not (folder/'ledger.json').exists() and not (folder/'habitat-export.geojson.gz').exists()
    receipt = rough_first.read_json(rough_first.receipt_path(tmp_path, 'synthetic-region'))
    assert receipt['pass'] is False and receipt['mode'] == 'control'

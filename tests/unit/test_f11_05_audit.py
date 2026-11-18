"""F11-05: an unlisted region's control archive must be a readable, supported PMTiles archive before publication.

Contract: ``control_receipt`` (the ordinary, no-reference branch) passes only a structurally readable PMTiles v3
vector archive: valid header (gzip directories, MVT tile type, supported tile compression), readable directories
and tiles that decode. ``publish.build`` refuses a rejected candidate on both branches and leaves the prior release
(archive and manifest) in place.
Believable bug: only the eight magic bytes were trusted, so ``b'PMTiles\\x03' + junk`` recorded ``unreadable``
yet ``pass=True`` and the build went on to publish an unusable map (or deleted the prior archive while refusing).
"""
import gzip
import zlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from skippercast.seafloor import rough_first
from tests.unit.test_rough_first_tile_spans import archive


def _pb(num, payload):
    def varint(n):
        out = bytearray()
        while True:
            out.append((n & 127) | (128 if n > 127 else 0))
            n >>= 7
            if not n:
                return bytes(out)
    return varint(num << 3 | 2) + varint(len(payload)) + payload


# One gzip Mapbox Vector Tile with a single (empty) layer: what a real archive stores per tile.
MVT = gzip.compress(_pb(3, _pb(1, b'habitat')), mtime=0)
MAGIC_ONLY = b'PMTiles\x03' + bytes(200)  # right prefix, zeroed header: compression byte is not gzip


def valid_archive():
    return archive(MVT)


def test_valid_ordinary_archive_passes_without_a_reference():
    receipt = rough_first.control_receipt('synthetic-region', valid_archive())
    assert (receipt['mode'], receipt['gate'], receipt['pass'], receipt['failed']) == ('control', None, True, [])
    assert 'unreadable' not in receipt['archive']
    assert receipt['archive']['per_zoom'] == {'12': {'tiles': 1, 'bytes': len(MVT)}}
    assert 'FAIL' not in rough_first.summary(receipt)


def test_magic_prefixed_invalid_header_fails():
    receipt = rough_first.control_receipt('synthetic-region', MAGIC_ONLY)
    assert receipt['pass'] is False
    assert receipt['failed'] == ['unreadable archive']
    assert receipt['archive']['unreadable'] == 'ValueError'
    assert 'FAIL, nothing published' in rough_first.summary(receipt)


def test_corrupt_directory_stream_fails_not_raises():
    good = valid_archive()
    root_length = int.from_bytes(good[16:24], 'little')
    # Same header and span, but the directory bytes are not valid gzip/deflate data.
    corrupt = good[:127] + bytes([0x1f, 0x8b, 8, 0]) + b'\xff' * (root_length - 4) + good[127 + root_length:]
    with pytest.raises((OSError, zlib.error)):
        gzip.decompress(corrupt[127:127 + root_length])
    receipt = rough_first.control_receipt('synthetic-region', corrupt)
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']


@pytest.mark.parametrize('offset, value, reason', [
    (98, 0, 'unsupported tile compression'),  # unknown
    (98, 3, 'unsupported tile compression'),  # brotli: not decoded by this pipeline
    (98, 4, 'unsupported tile compression'),  # zstd
    (99, 0, 'unsupported tile type'),         # unknown
    (99, 2, 'unsupported tile type'),         # PNG raster, not a vector archive
])
def test_unsupported_tile_header_fails(offset, value, reason):
    data = bytearray(valid_archive())
    data[offset] = value
    with pytest.raises(ValueError, match=reason):
        rough_first.read_tiles(bytes(data))
    receipt = rough_first.control_receipt('synthetic-region', bytes(data))
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']


@pytest.mark.parametrize('payload', [
    b'ABCD',                                           # not gzip although the header says so
    gzip.compress(b'\xff\xff\xff', mtime=0),           # gzip, but not a protobuf vector tile
    gzip.compress(_pb(1, b'habitat'), mtime=0),        # protobuf, but field 1 is not a layer
])
def test_undecodable_tile_payload_fails(payload):
    data = archive(payload)
    assert rough_first.read_tiles(data)  # the directory and spans are structurally fine
    receipt = rough_first.control_receipt('synthetic-region', data)
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
PRIOR_ARCHIVE, PRIOR_MANIFEST = b'prior archive bytes', b'{"prior": "release"}'


def _publish(tmp_path, written, **patches):
    from skippercast.seafloor import publish

    folder = tmp_path/'var/seafloor/public/synthetic-region'
    folder.mkdir(parents=True)
    (folder/'seafloor-synthetic-region.pmtiles').write_bytes(PRIOR_ARCHIVE)
    (folder/'manifest.json').write_bytes(PRIOR_MANIFEST)

    def build_archive(tool, layers, path, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(written)

    with patch.object(publish, 'region_layers', return_value=({'cells': [], 'habitat': []}, {}, NOW + timedelta(days=1))), \
            patch('scripts.build_map_tiles.build_vector_archive', side_effect=build_archive), \
            patch.multiple(rough_first, GateFailure=rough_first.GateFailure, **patches):
        with pytest.raises(rough_first.GateFailure) as refused:
            publish.build('synthetic-region', root=tmp_path, tool='fixture', now=NOW)
    return folder, refused.value


def _prior_release_untouched(tmp_path, folder):
    assert (folder/'seafloor-synthetic-region.pmtiles').read_bytes() == PRIOR_ARCHIVE
    assert (folder/'manifest.json').read_bytes() == PRIOR_MANIFEST
    assert sorted(p.name for p in folder.iterdir()) == ['manifest.json', 'seafloor-synthetic-region.pmtiles']
    assert not [p for p in (tmp_path/'var/seafloor').iterdir() if p.name.startswith('.stage-')]  # staging cleaned up


@pytest.mark.gis
def test_publish_refuses_unreadable_control_archive_and_keeps_prior_release(tmp_path):
    folder, error = _publish(tmp_path, MAGIC_ONLY)
    assert 'Unreadable seafloor archive' in str(error)
    _prior_release_untouched(tmp_path, folder)
    receipt = rough_first.read_json(rough_first.receipt_path(tmp_path, 'synthetic-region'))
    assert receipt['pass'] is False and receipt['mode'] == 'control'


@pytest.mark.gis
def test_publish_refuses_rejected_rough_first_archive_and_keeps_prior_release(tmp_path):
    rejected = {'mode': 'rough-first', 'pass': False, 'failed': ['unreadable archive']}
    (tmp_path/'catalog').mkdir()
    (tmp_path/rough_first.REFERENCE_FILE).write_text('{}')  # publish hashes the reference file it was given
    folder, error = _publish(tmp_path, MAGIC_ONLY, load_reference=lambda root, region: {'fixture': True},
                             evaluate=lambda *args, **kwargs: rejected)
    assert 'Rough-first size gate failed' in str(error)
    _prior_release_untouched(tmp_path, folder)

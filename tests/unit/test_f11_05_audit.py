"""F11-05: an unlisted region's control archive must be a readable, supported PMTiles archive before publication.

Contract: ``control_receipt`` (the ordinary, no-reference branch) passes only a structurally readable PMTiles v3
vector archive: valid header (gzip directories, MVT tile type, supported tile compression), readable directories
and tiles that decode. ``publish.build`` refuses a rejected candidate on both branches and leaves the prior release
(archive and manifest) in place.
Believable bugs: (1) a tile whose layer bytes are truncated or mistyped (``1a 01 ff``, ``18 01``) passed because only
the outer field numbers were checked, so an unreadable tile could publish; (2) only the eight magic bytes were trusted,
so ``b'PMTiles\\x03' + junk`` recorded ``unreadable`` yet ``pass=True`` and the build went on to publish an unusable
map (or deleted the prior archive while refusing).
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
NAMED = _pb(1, b'habitat')
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
    # Nested layer bytes: the outer tile looks like layers, but a layer cannot be decoded.
    gzip.compress(b'\x1a\x01\xff', mtime=0),               # layer is one truncated varint byte
    gzip.compress(b'\x18\x01', mtime=0),                   # field 3 is a varint, not a length-delimited layer
    gzip.compress(_pb(3, b'\x78\x02'), mtime=0),           # layer has a version but no name (field 1)
    gzip.compress(_pb(3, _pb(1, b'habitat')[:-1]), mtime=0),  # layer name is cut short of its declared length
    gzip.compress(_pb(3, b'\x08\x07'), mtime=0),           # layer name (field 1) sent as a varint
    gzip.compress(_pb(3, _pb(1, b'\xff\xfe')), mtime=0),   # layer name is not UTF-8
    gzip.compress(_pb(3, _pb(1, b'habitat') + b'\x28\x80'), mtime=0),  # layer extent: truncated varint
    gzip.compress(_pb(3, _pb(1, b'habitat') + b'\x2a\x00'), mtime=0),  # layer extent sent length-delimited
    gzip.compress(_pb(3, _pb(1, b'habitat') + _pb(2, b'\x20\x01\x22')), mtime=0),  # feature geometry cut off
    gzip.compress(_pb(3, _pb(1, b'habitat') + _pb(2, _pb(4, b'\x80'))), mtime=0),  # feature geometry: bad packed varint
    # Embedded Value messages (layer field 4) and keys (field 3) are decoded, not just length-checked.
    gzip.compress(b'\x1a\x08\x0a\x01a\x78\x02\x22\x01\xff', mtime=0),  # value is a truncated protobuf varint
    gzip.compress(_pb(3, NAMED + _pb(4, b'\x20\x80')), mtime=0),       # value int member: truncated varint
    gzip.compress(_pb(3, NAMED + _pb(4, _pb(1, b'\xff\xfe'))), mtime=0),  # value string member is not UTF-8
    gzip.compress(_pb(3, NAMED + _pb(4, b'\x08\x01')), mtime=0),       # value string member sent as a varint
    gzip.compress(_pb(3, NAMED + _pb(4, b'\x19\x00')), mtime=0),       # value double member: only one byte of eight
    gzip.compress(_pb(3, NAMED + _pb(4, b'')), mtime=0),               # value sets no member
    gzip.compress(_pb(3, NAMED + _pb(4, _pb(1, b'a') + b'\x20\x01')), mtime=0),  # value sets two members
    gzip.compress(_pb(3, NAMED + _pb(3, b'\xff\xfe')), mtime=0),       # tag key is not UTF-8
    # Feature tags and geometry type must be consistent with the layer.
    gzip.compress(_pb(3, NAMED + _pb(2, _pb(2, b'\x00\x00'))), mtime=0),  # tags point past empty key/value tables
    gzip.compress(_pb(3, NAMED + _pb(3, b'k') + _pb(4, _pb(1, b'v')) + _pb(2, _pb(2, b'\x00'))), mtime=0),  # odd tags
    gzip.compress(_pb(3, NAMED + _pb(3, b'k') + _pb(4, _pb(1, b'v')) + _pb(2, _pb(2, b'\x01\x00'))), mtime=0),  # key 1
    gzip.compress(_pb(3, NAMED + _pb(2, b'\x18\x09')), mtime=0),       # geometry type 9 does not exist
])
def test_undecodable_tile_payload_fails(payload):
    data = archive(payload)
    assert rough_first.read_tiles(data)  # the directory and spans are structurally fine
    receipt = rough_first.control_receipt('synthetic-region', data)
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']


def test_decoded_layer_with_keys_values_and_tags_passes():
    layer = (NAMED + _pb(3, b'id') + _pb(4, _pb(1, b'abc')) + _pb(4, b'\x20\x05') + _pb(4, b'\x19' + bytes(8))
             + _pb(2, b'\x08\x07' + _pb(2, b'\x00\x00') + b'\x18\x01' + _pb(4, b'\x09\x01\x02')))
    receipt = rough_first.control_receipt('synthetic-region', archive(gzip.compress(_pb(3, layer), mtime=0)))
    assert receipt['pass'] is True and receipt['failed'] == []


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

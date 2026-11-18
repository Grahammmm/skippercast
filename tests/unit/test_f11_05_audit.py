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
from tests._support import ROOT
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


def _varint_bytes(n):
    out = bytearray()
    while True:
        out.append((n & 127) | (128 if n > 127 else 0))
        n >>= 7
        if not n:
            return out


def _field(num, value):  # a varint field
    return bytes(_varint_bytes(num << 3)) + bytes(_varint_bytes(value))


def _layer(*, name=b'habitat', version=2, keys=(b'id',), values=(_pb(1, b'x'),), features=None, extra=b''):
    """One MVT layer: a polygon feature tagged id=x with a closed-ring geometry unless `features` overrides."""
    if features is None:
        geometry = bytes(_varint_bytes(1 | 1 << 3)) + bytes([2, 2]) + bytes(_varint_bytes(2 | 2 << 3)) + bytes([2, 0, 0, 2]) \
            + bytes(_varint_bytes(7 | 1 << 3))
        features = [_pb(2, bytes([0, 0])) + _field(3, 3) + _pb(4, geometry)]
    body = (_pb(1, name) if name is not None else b'') + (_field(15, version) if version is not None else b'')
    body += b''.join(_pb(3, k) for k in keys) + b''.join(_pb(4, v) for v in values)
    return body + b''.join(_pb(2, f) for f in features) + extra


def _tile(layer):
    return gzip.compress(_pb(3, layer), mtime=0)


# One gzip Mapbox Vector Tile with a single layer holding one polygon feature: what a real archive stores per tile.
MVT = _tile(_layer())
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


def _malformed_layers():
    ok_geometry = bytes([1 | 1 << 3, 2, 2])
    return {
        'truncated layer payload': gzip.compress(b'\x1a\x01\xff', mtime=0),  # field 3, length 1, a lone 0xff
        'overlong layer length': gzip.compress(b'\x1a\x7f' + _layer(), mtime=0),
        'layer without a name': _tile(_layer(name=None)),
        'layer name not utf-8': _tile(_layer(name=b'\xff\xfe')),
        'layer version missing': _tile(_layer(version=None)),
        'layer version unknown': _tile(_layer(version=9)),
        'name field is a varint': gzip.compress(_pb(3, _field(1, 1) + _field(15, 2)), mtime=0),
        'tag indexes a missing key': _tile(_layer(features=[_pb(2, bytes([5, 0]))])),
        'tag indexes a missing value': _tile(_layer(features=[_pb(2, bytes([0, 5]))])),
        'odd tag list': _tile(_layer(features=[_pb(2, bytes([0]))])),
        'unknown geometry type': _tile(_layer(features=[_field(3, 9)])),
        'geometry unknown command': _tile(_layer(features=[_pb(4, bytes([5]))])),
        'geometry parameters missing': _tile(_layer(features=[_pb(4, bytes([1 | 2 << 3, 2, 2]))])),
        'geometry must start with MoveTo': _tile(_layer(features=[_pb(4, bytes([2 | 1 << 3, 2, 2]))])),
        'point with a LineTo': _tile(_layer(features=[_field(3, 1) + _pb(4, ok_geometry + bytes([2 | 1 << 3, 2, 2]))])),
        'value with two fields': _tile(_layer(values=[_pb(1, b'x') + _pb(1, b'y')])),
        'value string not utf-8': _tile(_layer(values=[_pb(1, b'\xff')])),
        'feature field with the wrong wire type': _tile(_layer(features=[_pb(1, b'x')])),
    }


@pytest.mark.parametrize('name', list(_malformed_layers()))
def test_malformed_layer_payload_fails(name):
    data = archive(_malformed_layers()[name])
    assert rough_first.read_tiles(data)  # directory and spans are fine; only the tile body is malformed
    receipt = rough_first.control_receipt('synthetic-region', data)
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']


NAMED = _pb(1, b'habitat') + _field(15, 2)
LOW_LEVEL = [  # hand-built byte strings: each outer tile looks like layers, but a nested byte run cannot be decoded
    gzip.compress(b'\x18\x01', mtime=0),                                  # field 3 is a varint, not a layer
    gzip.compress(_pb(3, b'\x78\x02'), mtime=0),                          # layer has a version but no name
    gzip.compress(_pb(3, _pb(1, b'habitat')[:-1]), mtime=0),               # layer name is cut short of its length
    gzip.compress(_pb(3, b'\x08\x07'), mtime=0),                          # layer name sent as a varint
    gzip.compress(_pb(3, NAMED + b'\x28\x80'), mtime=0),                  # layer extent: truncated varint
    gzip.compress(_pb(3, NAMED + b'\x2a\x00'), mtime=0),                  # layer extent sent length-delimited
    gzip.compress(_pb(3, NAMED + _pb(2, b'\x20\x01\x22')), mtime=0),       # feature geometry cut off
    gzip.compress(_pb(3, NAMED + _pb(2, _pb(4, b'\x80'))), mtime=0),       # feature geometry: bad packed varint
    gzip.compress(b'\x1a\x08\x0a\x01a\x78\x02\x22\x01\xff', mtime=0),   # truncated protobuf varint in a value
    gzip.compress(_pb(3, NAMED + _pb(4, b'\x20\x80')), mtime=0),          # value int member: truncated varint
    gzip.compress(_pb(3, NAMED + _pb(4, _pb(1, b'\xff\xfe'))), mtime=0),   # value string member is not UTF-8
    gzip.compress(_pb(3, NAMED + _pb(4, b'\x08\x01')), mtime=0),          # value string member sent as a varint
    gzip.compress(_pb(3, NAMED + _pb(4, b'\x19\x00')), mtime=0),          # value double member: one byte of eight
    gzip.compress(_pb(3, NAMED + _pb(4, b'')), mtime=0),                  # value sets no member
    gzip.compress(_pb(3, NAMED + _pb(3, b'\xff\xfe')), mtime=0),          # tag key is not UTF-8
    gzip.compress(_pb(3, NAMED + _pb(2, _pb(2, b'\x00\x00'))), mtime=0),   # tags point past empty key/value tables
    gzip.compress(_pb(3, NAMED + _pb(3, b'k') + _pb(4, _pb(1, b'v')) + _pb(2, _pb(2, b'\x01\x00'))), mtime=0),  # key 1
    gzip.compress(_pb(3, NAMED + _pb(2, b'\x18\x09')), mtime=0),          # geometry type 9 does not exist
]


@pytest.mark.parametrize('payload', LOW_LEVEL)
def test_nested_byte_level_corruption_fails(payload):
    receipt = rough_first.control_receipt('synthetic-region', archive(payload))
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']


def test_decoded_layer_with_keys_values_and_tags_passes():
    layer = (NAMED + _pb(3, b'id') + _pb(4, _pb(1, b'abc')) + _pb(4, b'\x20\x05') + _pb(4, b'\x19' + bytes(8))
             + _pb(2, b'\x08\x07' + _pb(2, b'\x00\x00') + b'\x18\x01' + _pb(4, b'\x09\x01\x02')))
    receipt = rough_first.control_receipt('synthetic-region', archive(gzip.compress(_pb(3, layer), mtime=0)))
    assert receipt['pass'] is True and receipt['failed'] == []


def test_uncompressed_tiles_are_parsed_too():
    data = bytearray(archive(_pb(3, _layer())))
    data[98] = 1  # header: tiles stored uncompressed
    assert rough_first.control_receipt('synthetic-region', bytes(data))['pass'] is True
    data = bytearray(archive(b'\x1a\x01\xff'))
    data[98] = 1
    assert rough_first.control_receipt('synthetic-region', bytes(data))['pass'] is False


def _evaluate(control, candidate):
    reference = rough_first.load_reference(ROOT, 'morro-bay')
    with patch.object(rough_first, 'read_tiles', side_effect=[control, candidate]):
        return rough_first.evaluate('morro-bay', b'c', b'r', reference)


@pytest.mark.parametrize('zoom', [8, 12, 13, 14, 15])
def test_rough_first_fails_when_a_tile_is_corrupt_in_both_archives(zoom):
    """The detail zooms 12-15 compare byte-for-byte, so an identically corrupt tile used to pass the gate."""
    good = {(z, 0, 0): MVT for z in (8, 9, 10, 11, 12, 13, 14, 15)}
    corrupt = {**good, (zoom, 0, 0): gzip.compress(b'\x1a\x01\xff', mtime=0)}
    receipt = _evaluate(corrupt, corrupt)
    assert receipt['pass'] is False and receipt['failed'] == ['unreadable archive']
    assert receipt['error'].startswith('unreadable archive: ')
    # Only the candidate corrupt is rejected as well.
    assert _evaluate(good, corrupt)['failed'] == ['unreadable archive']
    assert _evaluate(corrupt, good)['failed'] == ['unreadable archive']


def test_rough_first_decodes_every_zoom_before_the_gate_items_run():
    good = {(z, 0, 0): MVT for z in (8, 9, 10, 11, 12, 13, 14, 15)}
    assert 'unreadable archive' not in _evaluate(good, good)['failed']


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

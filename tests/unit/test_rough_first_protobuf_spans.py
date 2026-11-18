"""Truncated protobuf payloads in MVT tiles must refuse, not read as complete habitat evidence."""
import gzip
from unittest.mock import patch

import pytest

from skippercast.seafloor import rough_first
from tests._support import ROOT


def varint(n):
    out = bytearray()
    while True:
        out.append((n & 127) | (128 if n > 127 else 0))
        n >>= 7
        if not n:
            return bytes(out)


def pb(num, payload):
    return varint(num << 3 | 2) + varint(len(payload)) + payload


def tile(extra=0):
    """Gzip MVT with one habitat feature; `extra` overstates the layer's declared length."""
    body = pb(1, b'habitat') + pb(3, b'id') + pb(4, pb(1, b'x')) + pb(2, pb(2, bytes([0, 0])))
    return gzip.compress(varint(3 << 3 | 2) + varint(len(body) + extra) + body, mtime=0)


def test_overlong_habitat_layer_refuses():
    assert rough_first.habitat_ids(tile()) == (1, {'x'})
    with pytest.raises(ValueError, match='truncated protobuf'):
        rough_first.habitat_ids(tile(1))


def test_truncated_fixed_width_fields_refuse():
    for wire, width in ((1, 8), (5, 4)):
        for n in range(width):
            with pytest.raises(ValueError, match='truncated protobuf'):
                rough_first._fields(bytes([1 << 3 | wire]) + bytes(n))
    with pytest.raises(ValueError, match='truncated protobuf'):  # overlong nested feature message
        rough_first.habitat_ids(gzip.compress(pb(3, pb(1, b'habitat') + bytes([2 << 3 | 2, 5]) + b'abc')))


def test_exact_end_and_empty_fields_control():
    assert rough_first._fields(bytes([9]) + bytes(8)) == [(1, bytes(8))]
    assert rough_first._fields(bytes([13]) + bytes(4)) == [(1, bytes(4))]
    assert rough_first._fields(bytes([10, 0])) == [(1, b'')]
    assert rough_first._fields(b'') == []
    assert rough_first.habitat_ids(tile()) == (1, {'x'})


def test_malformed_mvt_fails_content_gate():
    reference = rough_first.load_reference(ROOT, 'morro-bay')
    control = {(z, 0, 0): tile() for z in (8, 9, 10, 11, 12)}
    for candidate, valid in ((control, True), ({**control, (10, 0, 0): tile(1)}, False)):
        with patch.object(rough_first, 'read_tiles', side_effect=[control, candidate]), \
                patch.object(rough_first, 'decode_tiles'):  # isolate the content gate; decoding has its own tests
            item = rough_first.evaluate('morro-bay', b'c', b'r', reference)['gate']['item4_content_z9_11']
        assert item['pass'] is valid
        assert ('error' in item) is not valid
        if not valid:
            assert item['error'] == 'ValueError'

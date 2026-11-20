"""PMTiles tile payload spans must lie inside the declared tile-data section and the archive."""
import gzip
import struct

import pytest

from skippercast.seafloor import rough_first

TILE_ID = (4 ** 12 - 1) // 3  # first tile id of zoom 12 (z=12, x=0, y=0)


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def archive(payload=b'ABCD', *, entries=None, section=None, drop=0):
    """Single-directory archive; entries are (tile_id, run, size, stored_offset)."""
    entries = entries or [(TILE_ID, 1, len(payload), 1)]
    directory = varint(len(entries))
    last = 0
    for tid, *_ in entries:
        directory += varint(tid - last)
        last = tid
    for column in (1, 2, 3):
        directory += b''.join(varint(e[column]) for e in entries)
    root = gzip.compress(directory, mtime=0)
    section = len(payload) if section is None else section
    tiles = sum(e[1] for e in entries)
    header = b'PMTiles\x03' + struct.pack('<11Q', 127, len(root), 127 + len(root), 0, 0, 0,
                                          127 + len(root), section, tiles, len(entries), len(entries))
    header = header.ljust(127, b'\0')
    header = header[:96] + b'\x01\x02' + header[98:]
    data = header + root + payload
    return data[:len(data) - drop]


def test_truncated_tile_payload_refuses():
    data = archive(drop=1)
    with pytest.raises(ValueError):
        rough_first.read_tiles(data)
    receipt = rough_first.control_receipt('morro-bay', data)
    assert receipt['archive']['unreadable'] == 'ValueError'
    assert 'per_zoom' not in receipt['archive'] or not receipt['archive']['per_zoom']


def test_tile_span_cannot_escape_declared_section():
    with pytest.raises(ValueError):  # entry runs one byte past h[7]; backing bytes intact
        rough_first.read_tiles(archive(b'ABCDE', section=4, entries=[(TILE_ID, 1, 5, 1)]))
    with pytest.raises(ValueError):  # first entry with stored offset 0 resolves to -1
        rough_first.read_tiles(archive(entries=[(TILE_ID, 1, 4, 0)]))
    with pytest.raises(ValueError):  # zero-size entry
        rough_first.read_tiles(archive(entries=[(TILE_ID, 1, 0, 1)]))


def test_tile_span_exact_end_control():
    assert rough_first.read_tiles(archive()) == {(12, 0, 0): b'ABCD'}
    shared = archive(b'ABCDEF', entries=[(TILE_ID, 2, 4, 1), (TILE_ID + 5, 1, 2, 5)])
    tiles = rough_first.read_tiles(shared)
    assert set(tiles) == {rough_first._zxy(TILE_ID), rough_first._zxy(TILE_ID + 1), rough_first._zxy(TILE_ID + 5)}
    assert tiles[rough_first._zxy(TILE_ID + 1)] == b'ABCD' and tiles[rough_first._zxy(TILE_ID + 5)] == b'EF'


def test_declared_tile_data_section_truncated_boundary():
    with pytest.raises(ValueError):  # the single addressed entry fits, the declared section does not
        rough_first.read_tiles(archive(section=5))

"""Check PMTiles section layout at the digest index writer boundary."""
import hashlib
from io import BytesIO
import json
import struct

import pytest

from skippercast.relief import digests, pmtiles_v3


PAYLOAD = b'synthetic tile'
ROOT, METADATA, LEAVES, TILES = 8, 24, 40, 56


@pytest.fixture
def archive(tmp_path):
    path = pmtiles_v3.write_pmtiles(
        tmp_path / 'fixture.pmtiles', [((8, 0, 0), PAYLOAD)],
        metadata={}, bounds=(-1, -1, 1, 1), minzoom=8, maxzoom=8, center=(8, 0, 0),
    )
    return bytearray(path.read_bytes())


@pytest.mark.parametrize(('moved', 'other'), [
    (METADATA, ROOT), (LEAVES, ROOT), (TILES, ROOT),
    (LEAVES, METADATA), (TILES, METADATA), (LEAVES, TILES),
])
def test_overlapping_sections_never_emit_index(archive, tmp_path, moved, other):
    # In-file ranges alone do not prevent directory bytes being mistaken for tile data.
    start, length = struct.unpack_from('<2Q', archive, other)
    moved_length = struct.unpack_from('<Q', archive, moved + 8)[0]
    struct.pack_into('<2Q', archive, moved, start + length - 1, moved_length or 1)
    output = tmp_path / 'digests'
    with pytest.raises(digests.DigestError, match='sections overlap'):
        digests.write_index(BytesIO(archive), output)
    assert not output.exists()


@pytest.mark.parametrize('reordered', [False, True], ids=['writer-layout', 'tiles-before-metadata'])
def test_adjacent_sections_and_empty_leaves_can_be_indexed(archive, tmp_path, reordered):
    # The writer emits adjacent sections and no leaves for one tile. Neither a
    # different section order nor the position of an empty range implies overlap.
    assert struct.unpack_from('<Q', archive, LEAVES + 8)[0] == 0
    if reordered:
        metadata, metadata_len = struct.unpack_from('<2Q', archive, METADATA)
        tiles, tiles_len = struct.unpack_from('<2Q', archive, TILES)
        archive[metadata:] = archive[tiles:tiles + tiles_len] + archive[metadata:metadata + metadata_len]
        struct.pack_into('<Q', archive, METADATA, metadata + tiles_len)
        struct.pack_into('<Q', archive, LEAVES, metadata + 1)
        struct.pack_into('<Q', archive, TILES, metadata)

    output = tmp_path / 'digests'
    assert digests.write_index(BytesIO(archive), output) == {'tiles': 1, 'chunks': 1}
    assert json.loads((output / '8/0_0.json').read_bytes()) == [[0, 0, hashlib.sha256(PAYLOAD).hexdigest()]]

"""The relief archive index must agree with the advertised zoom range."""

from functools import partial
import gzip
import struct

import pytest

from skippercast.relief.pmtiles_v3 import write_pmtiles


_write_archive = partial(write_pmtiles, metadata={}, bounds=(-122, 35, -121, 36),
                         minzoom=1, maxzoom=3, center=(2, -121.5, 35.5))


@pytest.mark.parametrize('zoom', [0, 4], ids=['below-minimum', 'above-maximum'])
def test_out_of_range_tile_preserves_previous_archive(tmp_path, zoom):
    path = tmp_path / 'relief.pmtiles'
    _write_archive(path, [((2, 0, 0), b'previous')])
    previous = path.read_bytes()

    # These coordinates are valid at their own zoom, so coordinate validation
    # alone would let the second tile through and replace the archive.
    tiles = iter([((2, 0, 0), b'replacement'), ((zoom, 0, 0), b'out of range')])
    with pytest.raises(ValueError, match='zoom'):
        _write_archive(path, tiles)
    assert path.read_bytes() == previous


def test_unsorted_single_pass_tiles_encode_both_zoom_endpoints(tmp_path):
    class SinglePassTiles:
        started = False

        def __iter__(self):
            assert not self.started, 'writer tried to iterate the tiles twice'
            self.started = True
            return iter([((3, 0, 0), b'C'), ((1, 0, 0), b'A'), ((2, 0, 0), b'B')])

    path = _write_archive(tmp_path / 'relief.pmtiles', SinglePassTiles())
    archive = path.read_bytes()
    assert tuple(archive[100:102]) == (1, 3)
    root, root_size = struct.unpack_from('<2Q', archive, 8)
    data, data_size = struct.unpack_from('<2Q', archive, 56)
    # All fields are single-byte varints here. For x=y=0 the Hilbert
    # position within each zoom is 0, giving cumulative IDs 1, 5, 21.
    assert gzip.decompress(archive[root:root + root_size]) == bytes([
        3,             # entry count
        1, 4, 16,      # tile ID deltas (sorted, not in input order)
        1, 1, 1,       # run lengths
        1, 1, 1,       # payload lengths
        1, 0, 0,       # first offset + 1, then contiguous payloads
    ])
    assert archive[data:data + data_size] == b'ABC'

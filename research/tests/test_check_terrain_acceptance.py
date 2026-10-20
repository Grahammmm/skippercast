"""T13 checker internals that need no GIS stack: topology counts, triangulation, PNG decoding."""
import struct
import zlib

import pytest

from research.scripts import check_terrain_acceptance as module


def grid(text):
    return [[ch == '#' for ch in row] for row in text.strip().split()]


# Two separate supported regions; the left one has a one-cell enclosed hole,
# and a gap touches the right border.
TWO_REGIONS = grid('''
####..##
#.##..##
####..#.
####..##
''')


def faces_of(support):
    return sorted(module.expected_faces(support))


def test_topology_counts_holes_regions_and_border_gaps():
    facts = module.topology(TWO_REGIONS, faces_of(TWO_REGIONS))
    assert facts['grid_shape'] == [4, 8]
    assert facts['supported_cells'] == 22 and facts['unsupported_cells'] == 10
    assert facts['mask_components_4'] == 2 and facts['mask_components_8'] == 2
    assert facts['enclosed_holes'] == 1 and facts['enclosed_hole_cells'] == 1
    assert facts['border_gap_cells'] == 9
    # The renderer's fixed quad diagonal cuts the corner triangle (0,0),(1,0),(0,1)
    # off beside the hole, so the mesh has one more piece than the mask.
    assert facts['mesh_components'] == 3
    assert facts['mesh_components_spanning_mask_regions'] == 0
    # (3,6) and (3,7) sit beside the border gap at (2,7) and join no triangle.
    assert facts['supported_cells_in_no_triangle'] == 2


def test_no_expected_triangle_touches_an_unsupported_cell():
    for face in module.expected_faces(TWO_REGIONS):
        assert all(TWO_REGIONS[r][c] for r, c in face)
        rows, cols = {r for r, _ in face}, {c for _, c in face}
        assert max(rows) - min(rows) <= 1 and max(cols) - min(cols) <= 1


def test_a_bridging_triangle_is_counted_as_spanning_two_regions():
    bridge = ((0, 3), (0, 6), (1, 6))
    facts = module.topology(TWO_REGIONS, [*faces_of(TWO_REGIONS), tuple(sorted(bridge))])
    assert facts['mesh_components'] == 2
    assert facts['mesh_components_spanning_mask_regions'] == 1


def test_diagonal_touch_is_one_8_region_but_two_4_regions():
    diagonal = grid('''
##..
##..
..##
..##
''')
    facts = module.topology(diagonal, faces_of(diagonal))
    assert facts['mask_components_4'] == 2 and facts['mask_components_8'] == 1
    # The renderer's quad split never joins cells that only touch at a corner here.
    assert facts['mesh_components'] == 2


def test_fully_supported_grid_has_the_renderer_triangle_count():
    full = grid('\n'.join(['#' * 32] * 32))
    assert len(module.expected_faces(full)) == 2 * 31 * 31 == 1922


def png_bytes(rows, filters):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    height, width = len(rows), len(rows[0]) // 3
    raw, previous = b'', bytes(width * 3)
    for row, kind in zip(rows, filters):
        if kind == 0:
            encoded = row
        elif kind == 1:
            encoded = bytes((row[i] - (row[i - 3] if i >= 3 else 0)) & 255 for i in range(len(row)))
        else:
            encoded = bytes((row[i] - previous[i]) & 255 for i in range(len(row)))
        raw += bytes([kind]) + encoded
        previous = row
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def test_png_decoder_round_trips_filters(tmp_path):
    rows = [bytes([10, 20, 30, 40, 50, 60]), bytes([1, 2, 3, 250, 251, 252]), bytes([9, 9, 9, 0, 0, 0])]
    path = tmp_path / 'p.png'
    path.write_bytes(png_bytes(rows, [0, 1, 2]))
    width, height, decoded = module.decode_png(path)
    assert (width, height) == (2, 3) and decoded == rows
    assert module.pixel(decoded, 1, 1) == (250, 251, 252)


def test_png_decoder_rejects_corruption(tmp_path):
    data = bytearray(png_bytes([bytes(6)], [0]))
    data[20] ^= 1
    path = tmp_path / 'bad.png'
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        module.decode_png(path)


def test_context_digest_ignores_only_the_review_pointer():
    doc = dict(a=1, b=[1, 2], scientific_review=dict(path='x'))
    assert module.context_digest(doc) == module.context_digest(dict(a=1, b=[1, 2]))
    assert module.context_digest(doc) != module.context_digest(dict(a=2, b=[1, 2]))

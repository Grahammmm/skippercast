"""Palette validation at the PNG reader, independent of preview packaging."""
import struct
import zlib

import pytest

from scripts.relief.central_relief_preview_pair_png import validate_png
from tests.unit.test_central_relief_preview_pair import _chunk


def _indexed_png(width, height, rows, *, entries=1, depth=8, interlace=0):
    return (b'\x89PNG\r\n\x1a\n'
            + _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, 3, 0, 0, interlace))
            + _chunk(b'PLTE', bytes(range(3 * entries)))
            + _chunk(b'IDAT', zlib.compress(rows))
            + _chunk(b'IEND', b''))


def test_refuses_reconstructed_index_equal_to_palette_count():
    # Valid framing and a valid Sub filter can still decode to an undefined color.
    validate_png(_indexed_png(2, 1, b'\x01\x00\x00'), 2, 1)
    with pytest.raises(ValueError, match='palette index out of range'):
        validate_png(_indexed_png(2, 1, b'\x01\x00\x01'), 2, 1)


@pytest.mark.parametrize('width, entries, good, bad', [
    pytest.param(2, 2, b'\x00\x01\x01\x01\x01\xff', b'\x00\x01\x01\x01\x01\x01', id='sub'),
    pytest.param(1, 2, b'\x00\x01\x02\xff', b'\x00\x01\x02\x01', id='up'),
    pytest.param(2, 2, b'\x00\x01\x01\x03\x01\xff', b'\x00\x01\x01\x03\x01\x01', id='average'),
    pytest.param(2, 3, b'\x00\x01\x02\x04\xff\xff', b'\x00\x01\x02\x04\xff\x02', id='paeth'),
])
def test_checks_decoded_samples_not_filter_residuals(width, entries, good, bad):
    # 255 is a valid wrapped residual, not an index. In the bad row the last
    # residual is in range on its own; the predictor raises it to the palette size.
    validate_png(_indexed_png(width, 2, good, entries=entries), width, 2)
    with pytest.raises(ValueError, match='palette index out of range'):
        validate_png(_indexed_png(width, 2, bad, entries=entries), width, 2)


@pytest.mark.parametrize('depth, good, bad', [
    (1, b'\x02\x1f', b'\x02\x3f'),
    (2, b'\x02\x03', b'\x02\x07'),
    (4, b'\x02\x00\x0f', b'\x02\x00\x1f'),
])
def test_checks_final_packed_sample_but_ignores_padding(depth, good, bad):
    # First-row Up predicts zero; pack three pixels MSB-first. The unused
    # low bits are all ones even in the healthy tile and are not pixels.
    validate_png(_indexed_png(3, 1, good, depth=depth), 3, 1)
    with pytest.raises(ValueError, match='palette index out of range'):
        validate_png(_indexed_png(3, 1, bad, depth=depth), 3, 1)


def test_adam7_resets_previous_row_per_pass_not_per_scanline():
    # For 1×5 the nonempty passes hold rows (0), (4), (2), (1,3).
    # Every pass starts with packed index 1. In the last pass the second Up
    # row must use that predecessor: +0xc0 wraps to index 0, +0x40 gives 2.
    starts = b'\x02\x40' * 4
    good = _indexed_png(1, 5, starts + b'\x02\xc0', entries=2, depth=2, interlace=1)
    bad = _indexed_png(1, 5, starts + b'\x02\x40', entries=2, depth=2, interlace=1)
    validate_png(good, 1, 5)
    with pytest.raises(ValueError, match='palette index out of range'):
        validate_png(bad, 1, 5)

"""Audit explicit emitted IDs through the real fine-proof GeoTIFF reader."""
import numpy as np
import pytest

from skippercast.relief import fine_proof
from skippercast.relief.fine_emitted_tiles import audit_emitted_tiles


def _proof(path, z, *, x1=4, unproven_pixel=None):
    size = fine_proof.TILE
    shape = (size, size * (x1 - 4 + 1))
    bands = [np.full(shape, value) for value in (3., -10., 0.5)]
    if unproven_pixel is not None:
        for band in bands:
            band[unproven_pixel] = fine_proof.NODATA
    fine_proof.write(path, z, 4, 7, x1, 7, *bands)
    return path


def test_all_emitted_fine_tiles_are_certified(tmp_path):
    # An unproven neighbor was never emitted. Walking the proof rectangle
    # instead of the emitted set would wrongly fail this audit.
    p16 = _proof(tmp_path / 'a.tif', 16, x1=5, unproven_pixel=(0, 256))
    p17 = _proof(tmp_path / 'b.tif', 17)
    result = audit_emitted_tiles([(17, 4, 7), (15, 32767, 32767), (16, 4, 7), (17, 4, 7)], [p17, p16])
    assert result.passed
    assert result.certified == ((16, 4, 7), (17, 4, 7))
    assert result.missing_proof == result.uncertified == ()


def test_one_unproven_pixel_fails_the_emitted_tile(tmp_path):
    # An any-pixel or sample-only check could miss this last pixel.
    proof = _proof(tmp_path / 'proof.tif', 16, x1=5, unproven_pixel=(255, 511))
    result = audit_emitted_tiles([(16, 4, 7), (16, 5, 7)], [proof])
    assert not result.passed
    assert result.certified == ((16, 4, 7),)
    assert result.uncertified == ((16, 5, 7),)
    assert result.missing_proof == ()


def test_same_xy_at_other_zoom_is_not_matching_proof(tmp_path):
    # An XY-only lookup or fallback to the only raster would certify z17.
    proof = _proof(tmp_path / 'proof.tif', 16)
    result = audit_emitted_tiles([(16, 4, 7), (17, 4, 7)], [proof])
    assert not result.passed
    assert result.certified == ((16, 4, 7),)
    assert result.missing_proof == ((17, 4, 7),)
    assert result.uncertified == ()


def test_outside_matching_rectangle_is_not_certified(tmp_path):
    # The adjacent tile is still on the XYZ grid; checking only the presence
    # of a raster at z17 (or treating an empty slice as green) would pass it.
    proof = _proof(tmp_path / 'proof.tif', 17)
    result = audit_emitted_tiles([(17, 4, 7), (17, 5, 7)], [proof])
    assert not result.passed
    assert result.certified == ((17, 4, 7),)
    assert result.uncertified == ((17, 5, 7),)
    assert result.missing_proof == ()


@pytest.mark.parametrize('bad_id', [
    pytest.param(42, id='not-an-xyz-triple'),
    pytest.param((16, 4), id='missing-coordinate'),
    pytest.param((16, 4.0, 7), id='no-float-coercion'),
    pytest.param((False, 0, 0), id='boolean-is-not-a-zoom'),
    pytest.param((-1, 0, 0), id='negative-zoom'),
    pytest.param((15, 32768, 0), id='invalid-even-at-ignored-zoom'),
    pytest.param((17, 0, -1), id='negative-y'),
    pytest.param((18, 4, 7), id='unsupported-higher-zoom'),
])
def test_invalid_id_is_rejected_not_coerced_or_ignored(tmp_path, bad_id):
    # A loose cast or zoom filter before validation would hide malformed IDs.
    proof = _proof(tmp_path / 'proof.tif', 16)
    with pytest.raises(ValueError, match='emitted tile at index 1'):
        audit_emitted_tiles([(16, 4, 7), bad_id], [proof])


def test_unreadable_supplied_proof_is_not_reported_as_absent(tmp_path):
    # Swallowing the reader error would turn an invalid input into a mere gap.
    path = tmp_path / 'invalid.tif'
    path.write_bytes(b'not a raster')
    with pytest.raises(fine_proof.FineProofError, match='raster read failed'):
        audit_emitted_tiles([(16, 4, 7)], [path])


def test_duplicate_proof_zoom_refuses_ambiguous_input(tmp_path):
    # Last-file-wins would silently select conflicting evidence for z16.
    green = _proof(tmp_path / 'green.tif', 16)
    red = _proof(tmp_path / 'red.tif', 16, unproven_pixel=(0, 0))
    with pytest.raises(ValueError, match='multiple fine-proof rasters for z16'):
        audit_emitted_tiles([(16, 4, 7)], [green, red])

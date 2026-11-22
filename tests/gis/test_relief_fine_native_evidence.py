"""Exercise native-evidence vetoes at the real fine-proof file boundary."""

import numpy as np
import pytest

from skippercast.relief import fine_proof
from skippercast.relief.fine_native_evidence import prepare_bands

ZOOM, X, Y = 17, 41, 29
SHAPE = (fine_proof.TILE, fine_proof.TILE)
CELL = (37, 219)


@pytest.fixture
def evidence():
    return {
        'classes': np.full(SHAPE, 3, dtype='uint8'),
        'elevation': np.full(SHAPE, -10.125, dtype='float64'),
        'native_spacing': np.full(SHAPE, 0.75, dtype='float64'),
        'valid': np.ones(SHAPE, dtype=bool),
    }


def _roundtrip(path, bands):
    fine_proof.write(path, ZOOM, X, Y, X, Y, *bands)
    return fine_proof.read(path)


def test_full_measured_tile_roundtrips_and_certifies(tmp_path, evidence):
    # Closed depth bounds and spacing=1 qualify; precise, asymmetric samples
    # expose a flip, a Float32 round trip or use of nominal output pitch.
    evidence['elevation'][0, 1:4] = [-20, 0, np.nextafter(-10.125, -np.inf)]
    evidence['native_spacing'][1, 2:5] = [1, np.nextafter(1.0, 0.0), np.nextafter(0.0, 1.0)]
    proof = _roundtrip(tmp_path / 'proof.tif', prepare_bands(**evidence))

    assert proof.certified(ZOOM, X, Y)
    assert proof.proven.all()
    np.testing.assert_array_equal(proof.cls, evidence['classes'])
    np.testing.assert_array_equal(proof.elev, evidence['elevation'])
    np.testing.assert_array_equal(proof.spacing, evidence['native_spacing'])


@pytest.mark.parametrize('field,value', [
    pytest.param('classes', 0, id='no-class-evidence'),
    pytest.param('classes', 1, id='interpolated-is-not-measured'),
    pytest.param('classes', 2, id='unknown-is-not-measured'),
    pytest.param('classes', np.nan, id='nonfinite-class'),
    pytest.param('elevation', -21, id='depth-too-deep'),
    pytest.param('elevation', 1, id='elevation-above-water'),
    pytest.param('elevation', np.nextafter(-20.0, -np.inf), id='float64-just-below-minus-20'),
    pytest.param('elevation', np.nextafter(0.0, np.inf), id='float64-just-above-zero'),
    pytest.param('elevation', np.nan, id='nonfinite-elevation'),
    pytest.param('native_spacing', 2, id='native-spacing-too-coarse'),
    pytest.param('native_spacing', 0, id='zero-spacing-not-evidence'),
    pytest.param('native_spacing', np.nextafter(0.0, -np.inf), id='float64-just-below-zero-spacing'),
    pytest.param('native_spacing', np.nextafter(1.0, np.inf), id='float64-just-above-one-metre'),
    pytest.param('native_spacing', np.inf, id='nonfinite-spacing'),
    pytest.param('valid', False, id='invalid-despite-otherwise-passing-evidence'),
    pytest.param('valid', np.nan, id='nonfinite-validity-is-not-truthy'),
    pytest.param('classes', np.ma.masked, id='masked-measured-class'),
    pytest.param('elevation', np.ma.masked, id='masked-in-range-elevation'),
    pytest.param('native_spacing', np.ma.masked, id='masked-in-range-spacing'),
    pytest.param('valid', np.ma.masked, id='masked-true-validity'),
])
def test_one_veto_yields_exactly_one_unproven_cell(tmp_path, evidence, field, value):
    # A lone bad cell must not certify, leak a partial triple, or invalidate
    # its neighbours. Masked cases leave a passing value beneath the mask.
    band = evidence[field]
    if value is np.ma.masked:
        band = np.ma.array(band)
    elif not np.isfinite(value):
        band = band.astype('float64')
    band[CELL] = value
    evidence[field] = band

    bands = prepare_bands(**evidence)
    assert tuple(output[CELL] for output in bands) == (fine_proof.NODATA,) * 3
    proof = _roundtrip(tmp_path / 'proof.tif', bands)
    expected_proven = np.ones(SHAPE, dtype=bool)
    expected_proven[CELL] = False
    np.testing.assert_array_equal(proof.proven, expected_proven)
    assert not proof.certified(ZOOM, X, Y)


def test_does_not_broadcast_misaligned_evidence(evidence):
    # Broadcasting a one-row spacing array would fabricate evidence for the
    # other 255 rows. Reject it before there can be anything to write.
    evidence['native_spacing'] = evidence['native_spacing'][:1]
    with pytest.raises(ValueError, match='one real or boolean fine-proof tile'):
        prepare_bands(**evidence)

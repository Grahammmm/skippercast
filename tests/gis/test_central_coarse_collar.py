"""Synthetic coarse producer → aligned wet mask → collar report controls."""

import json

import numpy as np
import pytest
import rasterio as rio

from scripts.relief.central_coarse_collar import main
from skippercast.relief.coarse import write_coarse


TRANSFORM = rio.Affine(20, 0, 1000, 0, -20, 2000)
SHAPE = (4, 5)


def _inputs(tmp_path, samples, wet, *, mask_transform=TRANSFORM, validity=None, nodata=None):
    coarse = tmp_path / 'coarse.tif'
    mask = tmp_path / 'wet.tif'
    write_coarse(coarse, samples, TRANSFORM)
    if validity is not None:
        with rio.Env(GDAL_TIFF_INTERNAL_MASK=True), rio.open(coarse, 'r+') as dst:
            dst.nodata = nodata
            dst.write_mask(validity)
    with rio.open(mask, 'w', driver='GTiff', count=1, dtype='uint8', crs='EPSG:3310',
                  transform=mask_transform, height=wet.shape[0], width=wet.shape[1]) as dst:
        dst.write(wet, 1)
    return ['--coarse', str(coarse), '--wet-mask', str(mask)]


@pytest.mark.parametrize(('holes', 'collar', 'interior'), [
    pytest.param([(0, 0)], 1, 0, id='wet-collar-hole'),
    pytest.param([(1, 1)], 0, 1, id='equal-area-interior-hole'),
    pytest.param([(2, 4), (2, 3)], 1, 1, id='connected-gap-split-by-cell'),
])
def test_partition_missing_wet_cells(tmp_path, capsys, holes, collar, interior):
    """Catch a pooled total, double-counted corner or an entire edge-connected gap counted as collar."""
    samples = np.full(SHAPE, -120, dtype='float32')
    for cell in holes:
        samples[cell] = np.nan
    args = _inputs(tmp_path, samples, np.ones(SHAPE, dtype='uint8'))

    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        'kind': 'missing_estimated_grid_input',
        'outer_collar': {'cells': collar, 'area_m2': collar * 400},
        'interior': {'cells': interior, 'area_m2': interior * 400},
    }


def test_dry_collar_hole_is_not_a_gap(tmp_path, capsys):
    """Catch a nodata-only diagnostic that ignores the supplied wet mask."""
    samples = np.full(SHAPE, -10, dtype='float32')
    samples[3, 1] = np.nan
    wet = np.ones(SHAPE, dtype='uint8')
    wet[3, 1] = 0

    assert main(_inputs(tmp_path, samples, wet)) == 0
    assert json.loads(capsys.readouterr().out) == {
        'kind': 'missing_estimated_grid_input',
        'outer_collar': {'cells': 0, 'area_m2': 0},
        'interior': {'cells': 0, 'area_m2': 0},
    }


@pytest.mark.parametrize(('sample', 'collar', 'interior'), [
    pytest.param(-9999, 8, 1, id='finite-nodata-marked-valid'),
    pytest.param(-120, 0, 0, id='valid-finite-elevation'),
])
def test_internal_validity_mask_does_not_hide_band_nodata(tmp_path, capsys, sample, collar, interior):
    """Trusting only the GDAL mask and finiteness undercounts a finite band sentinel."""
    shape = (3, 3)
    args = _inputs(tmp_path, np.full(shape, sample, dtype='float32'), np.ones(shape, dtype='uint8'),
                   validity=np.ones(shape, dtype=bool), nodata=-9999)

    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        'kind': 'missing_estimated_grid_input',
        'outer_collar': {'cells': collar, 'area_m2': collar * 400},
        'interior': {'cells': interior, 'area_m2': interior * 400},
    }


def test_internal_validity_mask_preserves_dry_and_masked_cells(tmp_path, capsys):
    """Catch counting dry nodata or replacing GDAL validity with the nodata comparison."""
    samples = np.full((3, 3), -120, dtype='float32')
    wet = np.ones(samples.shape, dtype='uint8')
    validity = np.ones(samples.shape, dtype=bool)
    samples[0, (0, 2)] = -9999  # Dry and wet sentinels flank a valid wet elevation.
    wet[0, 0] = 0
    validity[1, 1] = False  # Finite non-sentinel, but invalid per GDAL.

    assert main(_inputs(tmp_path, samples, wet, validity=validity, nodata=-9999)) == 0
    assert json.loads(capsys.readouterr().out) == {
        'kind': 'missing_estimated_grid_input',
        'outer_collar': {'cells': 1, 'area_m2': 400},
        'interior': {'cells': 1, 'area_m2': 400},
    }


def test_refuses_same_shape_mask_shifted_one_cell(tmp_path, capsys):
    """A shape-only join silently pairs each coarse cell with its neighbour's wet flag."""
    args = _inputs(tmp_path, np.full(SHAPE, -10, dtype='float32'), np.ones(SHAPE, dtype='uint8'),
                   mask_transform=TRANSFORM @ rio.Affine.translation(1, 0))

    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    result = capsys.readouterr()
    assert not result.out
    assert 'wet mask must share the coarse grid shape, CRS and transform' in result.err

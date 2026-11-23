"""Synthetic coarse producer → aligned wet mask → collar report controls."""

import json

import numpy as np
import pytest
import rasterio as rio

from scripts.relief.central_coarse_collar import main
from skippercast.relief.coarse import write_coarse


TRANSFORM = rio.Affine(20, 0, 1000, 0, -20, 2000)
SHAPE = (4, 5)


def _inputs(tmp_path, samples, wet, *, mask_transform=TRANSFORM):
    coarse = tmp_path / 'coarse.tif'
    mask = tmp_path / 'wet.tif'
    write_coarse(coarse, samples, TRANSFORM)
    with rio.open(mask, 'w', driver='GTiff', count=1, dtype='uint8', crs='EPSG:3310',
                  transform=mask_transform, height=SHAPE[0], width=SHAPE[1]) as dst:
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

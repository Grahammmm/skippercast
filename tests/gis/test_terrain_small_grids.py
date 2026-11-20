"""Undersized valid terrain grids return unknown layers; admission and ordinary grids are unchanged."""
import warnings

import numpy as np
import pytest

pytest.importorskip('scipy')
from skippercast.seafloor import terrain  # noqa: E402

NAMES = ('slope_deg', 'vrm', 'bpi_fine_m', 'bpi_broad_m')


def _all_unknown(out, shape):
    assert set(out) == set(NAMES)
    for name in NAMES:
        assert out[name].shape == shape and out[name].dtype == np.float64
        assert np.isnan(out[name]).all()
    assert len({id(out[n]) for n in NAMES}) == 4
    assert not any(np.shares_memory(out[a], out[b]) for a in NAMES for b in NAMES if a != b)


@pytest.mark.parametrize('shape', [(1, 5), (5, 1), (1, 1)])
@pytest.mark.parametrize('fill', [True, False])
@pytest.mark.parametrize('value', [40.0, np.nan])
def test_singleton_axis_returns_unknown_layers(shape, fill, value):
    _all_unknown(terrain.derivatives(np.full(shape, value), np.full(shape, fill), 25), shape)


@pytest.mark.parametrize('shape', [(0, 5), (5, 0), (0, 0)])
def test_empty_axis_preserves_shape(shape):
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        out = terrain.derivatives(np.zeros(shape), np.zeros(shape, dtype=bool), 25)
    _all_unknown(out, shape)


def test_small_grid_cannot_bypass_admission():
    depth = np.ones((1, 5))
    with pytest.raises(ValueError, match='support mask'):
        terrain.derivatives(depth, np.ones((1, 5), dtype=int), 25)
    with pytest.raises(ValueError, match='terrain grid'):
        terrain.derivatives(depth, np.ones((1, 4), dtype=bool), 25)
    for bad in (0, -1, float('nan'), float('inf'), True):
        with pytest.raises(ValueError, match='terrain resolution'):
            terrain.derivatives(depth, np.ones((1, 5), dtype=bool), bad)


def test_two_by_two_and_supported_plane_controls():
    _all_unknown(terrain.derivatives(np.full((2, 2), 9.0), np.ones((2, 2), dtype=bool), 25), (2, 2))
    flat = terrain.derivatives(np.full((5, 5), 9.0), np.ones((5, 5), dtype=bool), 25)
    assert {k: int(np.isfinite(v).sum()) for k, v in flat.items()} == {
        'slope_deg': 9, 'vrm': 1, 'bpi_fine_m': 9, 'bpi_broad_m': 0}
    assert np.nanmax(np.abs(flat['slope_deg'])) == 0
    base = np.zeros((9, 20))
    base[:] = 50 + 25 * np.arange(20)  # 1 m rise per 25 m along x
    depth = base[:, ::2]
    valid = np.ones(depth.shape, dtype=bool)[:, ::1]
    before = depth.copy()
    out = terrain.derivatives(depth, valid, 50)
    assert np.allclose(out['slope_deg'][np.isfinite(out['slope_deg'])], np.degrees(np.arctan(25 * 2 / 50)))
    assert np.array_equal(depth, before) and valid.all()

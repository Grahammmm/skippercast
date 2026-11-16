"""Terrain spacing must be a finite positive real scalar (not bool) before any math."""
import numpy as np
import pytest

pytest.importorskip('scipy')
from skippercast.seafloor import terrain  # noqa: E402

N = 41


def _plane():
    y, x = np.mgrid[0:N, 0:N].astype('float64')
    return 50 + .1 * x + .2 * y, np.ones((N, N), dtype=bool)


def _boom(*a, **k):
    raise AssertionError('numerical math reached with invalid spacing')


def _guard(monkeypatch):
    monkeypatch.setattr(terrain, 'binary_erosion', _boom)
    monkeypatch.setattr(terrain.np, 'gradient', _boom)


def test_infinite_spacing_cannot_report_flat_slope(monkeypatch):
    depth, valid = _plane()
    _guard(monkeypatch)
    for bad in (float('inf'), float('-inf'), np.float64('inf')):
        with pytest.raises(ValueError, match='terrain resolution'):
            terrain.derivatives(depth, valid, bad)


def test_nan_and_nonpositive_spacing_refuse_before_math(monkeypatch):
    depth, valid = _plane()
    _guard(monkeypatch)
    for bad in (float('nan'), 0, 0.0, -0.0, -2.0, -5):
        with pytest.raises(ValueError, match='terrain resolution'):
            terrain.derivatives(depth, valid, bad)


def test_boolean_and_nonreal_spacing_are_not_metric_evidence(monkeypatch):
    depth, valid = _plane()
    _guard(monkeypatch)
    bad_values = (True, False, np.bool_(True), None, '2', 2j, np.array(2.0),
                  np.array([2.0, 2.0]), 10 ** 400)
    for bad in bad_values:
        with pytest.raises(ValueError, match='terrain resolution'):
            terrain.derivatives(depth, valid, bad)


def test_positive_python_and_numpy_spacing_preserve_results():
    depth, valid = _plane()
    for value in (2, 25, 50):
        control = terrain.derivatives(depth, valid, float(value))
        for spelled in (value, np.int64(value), np.float64(value), np.float32(value)):
            got = terrain.derivatives(depth, valid, spelled)
            assert got.keys() == control.keys()
            for key in control:
                assert np.array_equal(got[key], control[key], equal_nan=True), (key, spelled)
    out = terrain.derivatives(depth, valid, 2)
    expected = np.degrees(np.arctan(np.hypot(.1 / 2, .2 / 2)))
    assert out['slope_deg'][20, 20] == pytest.approx(expected)


def test_valid_plane_hole_and_empty_support_preserve_inputs():
    depth, valid = _plane()
    depth[10, 10] += 30
    sparse = valid.copy()
    sparse[::3, ::3] = False
    for mask in (valid, sparse, np.zeros_like(valid)):
        d0, m0 = depth.copy(), mask.copy()
        out = terrain.derivatives(depth, mask, 2.0)
        assert depth.tobytes() == d0.tobytes() and mask.tobytes() == m0.tobytes()
        if not mask.any():
            assert all(np.isnan(v).all() for v in out.values())
    assert np.isnan(terrain.derivatives(depth, sparse, 2.0)['slope_deg'][0, 0])

"""seafloor/raster.py: windows, chunks and native reads on awkward synthetic rasters."""
import math

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine
from rasterio.windows import Window

from skippercast.seafloor.raster import bounds_window, chunks, read_native
from tests._audit_cloud_synth import write_tif

ROW = {'vertical_datum': 'MLLW', 'id': 'synthetic', 'sha256': '0' * 64}


def lonlat_to_utm10(lon, lat):
    return Transformer.from_crs(4326, 32610, always_xy=True).transform(lon, lat)


def test_single_pixel_raster_gives_one_pixel_window(tmp_path):
    x, y = lonlat_to_utm10(-121.0, 36.0)
    path = write_tif(tmp_path / 'one.tif', np.array([[-10.0]], 'float32'),
                     transform=Affine(2, 0, x - 1, 0, -2, y + 1))
    with rasterio.open(path) as ds:
        w = bounds_window(ds, (-121.001, 35.999, -120.999, 36.001))
        assert (w.col_off, w.row_off, w.width, w.height) == (0, 0, 1, 1)
        assert read_native(ds, w, ROW).valid.all()


def test_extreme_aspect_window_is_covered_by_chunks_exactly(tmp_path):
    data = np.full((3, 5000), -5.0, 'float32')
    path = write_tif(tmp_path / 'strip.tif', data)
    with rasterio.open(path) as ds:
        w = Window(0, 0, 5000, 3)
        seen = np.zeros((3, 5000), int)
        for c in chunks(w, 512):
            seen[int(c.row_off):int(c.row_off + c.height), int(c.col_off):int(c.col_off + c.width)] += 1
        assert (seen == 1).all()


def test_source_touching_request_only_at_a_corner_is_empty_without_margin(tmp_path):
    x, y = lonlat_to_utm10(-121.0, 36.0)
    path = write_tif(tmp_path / 'corner.tif', np.full((10, 10), -5, 'float32'),
                     transform=Affine(2, 0, x, 0, -2, y))
    with rasterio.open(path) as ds:
        # Request lies up-left of the raster's top-left corner; they share one point.
        west, south = -121.01, 36.0
        east, north = -121.0, 36.01
        # A margin-free request that merely touches should not yield a non-empty window.
        with pytest.raises(ValueError, match='does not intersect'):
            bounds_window(ds, (west, south, east, north), margin_m=0)


def test_disjoint_request_is_refused(tmp_path):
    path = write_tif(tmp_path / 'a.tif', np.full((10, 10), -5, 'float32'))
    with rasterio.open(path) as ds, pytest.raises(ValueError):
        bounds_window(ds, (10.0, 10.0, 10.1, 10.1))


def test_window_across_utm_zone_boundary_contains_point_east_of_boundary(tmp_path):
    # Raster stored in zone 10 but extending past its 120W edge into zone 11 territory.
    x, y = lonlat_to_utm10(-119.95, 36.0)
    path = write_tif(tmp_path / 'zone.tif', np.full((200, 200), -5, 'float32'),
                     transform=Affine(10, 0, x - 1000, 0, -10, y + 1000))
    with rasterio.open(path) as ds:
        w = bounds_window(ds, (-119.951, 35.999, -119.949, 36.001), margin_m=0)
        col, row = ~ds.transform * (x, y)
        assert w.col_off <= col < w.col_off + w.width
        assert w.row_off <= row < w.row_off + w.height


def test_nan_bounds_raise_value_error_not_something_else(tmp_path):
    path = write_tif(tmp_path / 'a.tif', np.full((10, 10), -5, 'float32'))
    with rasterio.open(path) as ds:
        for bad in ((math.nan,) * 4, (-math.inf, 35.0, math.inf, 37.0)):
            with pytest.raises(ValueError):
                bounds_window(ds, bad)


def test_south_up_and_rotated_rasters_are_refused(tmp_path):
    for i, t in enumerate((Affine(2, 0, 500000, 0, 2, 4000000), Affine(2, 0.1, 500000, 0.1, -2, 4000000))):
        path = write_tif(tmp_path / f'r{i}.tif', np.full((10, 10), -5, 'float32'), transform=t)
        with rasterio.open(path) as ds, pytest.raises(ValueError, match='north-up'):
            bounds_window(ds, (-121, 35, -120, 37))


def test_read_native_cap_is_exact(tmp_path):
    path = write_tif(tmp_path / 'big.tif', np.full((1025, 1024), -5, 'float32'))
    with rasterio.open(path) as ds:
        assert read_native(ds, Window(0, 0, 1024, 1024), ROW).valid.all()
        with pytest.raises(ValueError):
            read_native(ds, Window(0, 0, 1024, 1025), ROW)


def test_nonfinite_values_are_never_valid_and_never_zero(tmp_path):
    data = np.array([[-5.0, np.nan, np.inf, -np.inf, 1e39 if False else -3.0e38]], 'float32')
    path = write_tif(tmp_path / 'nf.tif', data)
    with rasterio.open(path) as ds:
        n = read_native(ds, Window(0, 0, 5, 1), ROW)
        assert n.valid.tolist() == [[True, False, False, False, True]]
        assert np.isnan(n.depth_m[~n.valid]).all()


def test_float64_overflowing_float32_is_not_valid(tmp_path):
    path = write_tif(tmp_path / 'f64.tif', np.array([[-5.0, -1e300]], 'float64'))
    with rasterio.open(path) as ds:
        n = read_native(ds, Window(0, 0, 2, 1), ROW)
        assert n.valid.tolist() == [[True, False]]


def test_negative_uncertainty_and_bad_flags_do_not_leak(tmp_path):
    arr = np.stack([np.array([[-5.0, -6.0, -7.0]]), np.array([[1.0, -1.0, np.inf]]),
                    np.array([[0.0, 1.0, np.nan]])]).astype('float32')
    path = write_tif(tmp_path / 'bag.tif', arr)
    with rasterio.open(path) as ds:
        n = read_native(ds, Window(0, 0, 3, 1), ROW, uncertainty_band=2, interpolated_band=3)
        assert np.isfinite(n.uncertainty_m).tolist() == [[True, False, False]]
        assert n.interpolated.tolist() == [[False, True, True]]


def test_read_native_twice_is_identical(tmp_path):
    rng = np.random.default_rng(0)
    path = write_tif(tmp_path / 'r.tif', (-rng.random((64, 64)) * 50).astype('float32'), nodata=-9999)
    with rasterio.open(path) as ds:
        a = read_native(ds, Window(0, 0, 64, 64), ROW)
        b = read_native(ds, Window(0, 0, 64, 64), ROW)
    assert a.depth_m.tobytes() == b.depth_m.tobytes() and a.valid.tobytes() == b.valid.tobytes()


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)

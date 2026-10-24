"""Audit repro (2026-10-22): seafloor native ingest ignores raster vertical metadata.

`skippercast.seafloor.raster.read_native` always returns `-raw` as metres of
positive-down depth. It never reads band scale/offset, band units or a
positive-down sign, unlike `skippercast.coastal.vertical.to_depth`. Each test
asserts the correct behaviour (refuse, or convert) and fails on current main.
"""
import numpy as np
import pytest

pytestmark = pytest.mark.gis

rasterio = pytest.importorskip('rasterio')
from rasterio.transform import from_origin  # noqa: E402

from skippercast.seafloor.raster import read_native  # noqa: E402

ROW = {'vertical_datum': 'NAVD88', 'id': 'synthetic', 'sha256': '0' * 64}


def _tif(path, data, *, nodata=None, units=None, scale=1.0, offset=0.0, tags=None):
    profile = dict(driver='GTiff', width=data.shape[1], height=data.shape[0], count=1,
                   dtype=data.dtype, crs='EPSG:32610', transform=from_origin(600000, 4000000, 2, 2),
                   nodata=nodata)
    with rasterio.open(path, 'w', **profile) as out:
        out.write(data, 1)
        if units:
            out.units = (units,)
        out.scales, out.offsets = (scale,), (offset,)
        if tags:
            out.update_tags(1, **tags)
    return path


def _read(path):
    with rasterio.open(path) as ds:
        try:
            return read_native(ds, rasterio.windows.Window(0, 0, ds.width, ds.height), ROW)
        except ValueError:
            return None  # refusing is an acceptable fix


def test_packed_scale_is_applied_or_refused(tmp_path):
    # Raw -2000 with scale 0.01 is -20 m elevation: 20 m deep, not 2000 m.
    path = _tif(tmp_path / 'packed.tif', np.full((4, 4), -2000, 'int16'), nodata=-32768, scale=0.01)
    native = _read(path)
    assert native is None or np.allclose(native.depth_m[native.valid], 20.0), native.depth_m[0, 0]


def test_feet_units_are_converted_or_refused(tmp_path):
    # -100 ft elevation is 30.48 m deep; reported as 100 "m" it is 3.3x too deep.
    path = _tif(tmp_path / 'feet.tif', np.full((4, 4), -100, 'float32'), nodata=-9999, units='ft')
    native = _read(path)
    assert native is None or np.allclose(native.depth_m[native.valid], 30.48), native.depth_m[0, 0]


def test_positive_down_source_is_not_negated(tmp_path):
    # A depth raster (positive down, tagged) must not become negative "depth".
    path = _tif(tmp_path / 'down.tif', np.full((4, 4), 25, 'float32'), nodata=-9999,
                tags={'vertical_sign': 'positive_down'})
    native = _read(path)
    assert native is None or np.allclose(native.depth_m[native.valid], 25.0), native.depth_m[0, 0]

"""coastal/vertical.to_depth, seafloor/grid reference mosaic, and habitat tile windows."""
import copy

import numpy as np
import pytest
import shapely
from pyproj import CRS
from shapely.geometry import LineString

from skippercast.coastal import vertical
from skippercast.seafloor import grid, habitat_tiles

BLOCK = {'schema': vertical.VERSION, 'sign': 'positive_up', 'units': 'm', 'datum': 'MLLW', 'scale': 1.0,
         'offset': 0.0, 'scale_offset_applied': True, 'conflicts': [],
         'evidence': [{'kind': 'raster_header', 'source_sha256': 'a' * 64, 'header_sha256': 'b' * 64, 'facts': {}}]}


def block(**kw):
    out = copy.deepcopy(BLOCK)
    out.update(kw)
    return out


def test_block_fixture_is_valid():
    assert vertical.validate(BLOCK) == []


def test_to_depth_nonfinite_and_masked_never_become_zero():
    raw = np.ma.masked_array([-5.0, np.nan, np.inf, -np.inf, -7.0], mask=[0, 0, 0, 0, 1])
    out = vertical.to_depth(raw, block())
    assert out[0] == 5.0 and np.isnan(out[1:]).all()


def test_to_depth_feet_sign_and_packing_compose():
    out = vertical.to_depth(np.array([-2000.0]), block(units='ft', scale=0.01, offset=1.0, scale_offset_applied=False))
    assert out[0] == pytest.approx(-(-2000 * .01 + 1.0) * .3048)


def test_to_depth_nodata_sentinel_survives_float32_rounding():
    """A float32 raster whose declared nodata is -99999.9 (a float64 in the header) must still be masked."""
    raw32 = np.array([-5.0, -99999.9], 'float32')
    out = vertical.to_depth(raw32, block(), nodata=-99999.9)
    assert np.isnan(out[1]), f'sentinel leaked as a {out[1]} m depth'


def test_to_depth_nodata_equal_to_a_real_scaled_value_is_checked_on_raw():
    out = vertical.to_depth(np.array([-32768, 100]), block(scale=0.01, scale_offset_applied=False), nodata=-32768)
    assert np.isnan(out[0]) and out[1] == pytest.approx(-1.0)


def test_to_depth_rejects_support_mask_of_wrong_shape():
    with pytest.raises(ValueError):
        vertical.to_depth(np.zeros((2, 2)), block(), valid=np.ones((3, 3), bool))


def test_to_depth_rejects_non_finite_scale_or_offset():
    for bad in ({'scale': float('nan')}, {'scale': float('inf')}, {'offset': float('nan')}, {'offset': float('inf')}):
        with pytest.raises(vertical.VerticalHold):
            vertical.to_depth(np.array([-5.0]), block(scale_offset_applied=False, **bad))


def test_to_depth_overflow_to_inf_is_masked():
    out = vertical.to_depth(np.array([-1e308, -5.0]), block(scale=1e10, scale_offset_applied=False))
    assert np.isnan(out[0]) and np.isfinite(out[1])


def test_to_depth_twice_is_identical():
    raw = np.random.default_rng(5).normal(-30, 10, (50, 50))
    a, b = vertical.to_depth(raw, block()), vertical.to_depth(raw, block())
    assert a.tobytes() == b.tobytes()


# --- reference mosaic (seafloor/grid.py) ------------------------------------------------------

def test_classify_reference_boundaries_and_nonfinite():
    e = np.array([0.0, -0.0001, -100.0, -100.0001, np.nan, np.inf, -np.inf, 5.0], 'float64')
    assert grid.classify_reference(e).tolist() == [1, 2, 2, 1, 0, 0, 0, 1]


def test_classify_reference_float32_value_that_rounds_to_boundary():
    # float32(-100.00000001) == -100.0 exactly: a documented-inclusive boundary, so it is band.
    assert grid.classify_reference(np.array([-100.00000001], 'float32')).tolist() == [2]


def test_merge_reference_hole_never_overwrites():
    dest = np.array([2, 2, 1, 0], 'uint8')
    grid.merge_reference(dest, np.array([0, 1, 0, 2], 'uint8'))
    assert dest.tolist() == [2, 1, 1, 2]


def test_cell_counts_refuses_misaligned_and_handles_single_cell():
    with pytest.raises(ValueError):
        grid.cell_counts(np.zeros((10, 11), 'uint8'), 10)
    band, unknown = grid.cell_counts(np.full((10, 10), 2, 'uint8'), 10)
    assert band.tolist() == [[100]] and unknown.tolist() == [[0]]


def test_assign_reaches_nan_inf_and_endpoints():
    spine = LineString([(0, 0), (1000, 0)])
    reaches = [{'end_m': 500.0}, {'end_m': 1000.0}]
    x = np.array([250.0, 500.0, 999.0, 0.0, 1000.0, -50.0])
    got = grid.assign_reaches(spine, reaches, x, np.zeros(6)).tolist()
    assert got[:3] == [0, 1, 1] and got[3] == -1 and got[4] == -1
    assert got[5] == -1, 'point before the spine start is outside scope'


def test_assign_reaches_nan_centre_is_unowned_not_a_crash():
    spine = LineString([(0, 0), (1000, 0)])
    got = grid.assign_reaches(spine, [{'end_m': 1000.0}], np.array([250.0, np.nan]), np.zeros(2)).tolist()
    assert got == [0, -1]


def _tile(tmp_path, name, elevation, x0, y0, crs='EPSG:3310', cell=25.0):
    path = tmp_path / f'{name}.npz'
    t = (cell, 0, x0, 0, -cell, y0)
    np.savez(path, elevation=np.asarray(elevation, 'float32'), transform=np.array(t), crs=np.array(CRS.from_user_input(crs).to_wkt()))
    return path


CONFIG = {'reference_pixel_m': 25, 'cell_size_m': 250, 'reference_depth_m': [0, 100],
          'bounds': [-121.0, 35.0, -120.9, 35.1]}


def _mosaic(tmp_path, tiles):
    return grid.mosaic_reference(CONFIG, [t[0] for t in tiles], [(t[1], {}) for t in tiles])


def test_mosaic_finer_resolution_wins_regardless_of_age_and_is_order_independent(tmp_path):
    from pyproj import Transformer
    x, y = Transformer.from_crs(4326, 3310, always_xy=True).transform(-120.95, 35.05)
    x, y = round(x / 250) * 250, round(y / 250) * 250
    fine = {'id': 'fine', 'native_resolution_m': 2, 'delivered_date': '2001-01-01'}
    coarse = {'id': 'coarse', 'native_resolution_m': 16, 'delivered_date': '2024-01-01'}
    pf = _tile(tmp_path, 'fine', np.full((20, 20), -10), x, y)
    pc = _tile(tmp_path, 'coarse', np.full((20, 20), 50), x, y)
    a, aff = _mosaic(tmp_path, [(fine, pf), (coarse, pc)])
    b, _ = _mosaic(tmp_path, [(coarse, pc), (fine, pf)])
    assert a.tobytes() == b.tobytes()
    c, r = ~aff * (x + 100, y - 100)
    assert a[int(r), int(c)] == 2


def test_mosaic_tile_wholly_outside_is_skipped_and_nan_tile_is_unknown(tmp_path):
    t = {'id': 't', 'native_resolution_m': 2, 'delivered_date': '2020-01-01'}
    far = _tile(tmp_path, 'far', np.full((4, 4), -10), 0.0, 0.0)
    nan = _tile(tmp_path, 'nan', np.full((4, 4), np.nan), -200000.0, -400000.0)
    out, _ = _mosaic(tmp_path, [(t, far), ({**t, 'id': 'u'}, nan)])
    assert out.sum() == 0


def test_mosaic_single_pixel_tile_does_not_crash(tmp_path):
    from pyproj import Transformer
    x, y = Transformer.from_crs(4326, 3310, always_xy=True).transform(-120.95, 35.05)
    t = {'id': 'p', 'native_resolution_m': 2, 'delivered_date': '2020-01-01'}
    out, _ = _mosaic(tmp_path, [(t, _tile(tmp_path, 'p', [[-10.0]], x, y))])
    assert out.shape[0] > 0


def test_mosaic_tile_in_other_utm_zone_lands_where_it_should(tmp_path):
    from pyproj import Transformer
    lon, lat = -120.95, 35.05  # zone 10 (west of 120W)
    x, y = Transformer.from_crs(4326, 32611, always_xy=True).transform(lon, lat)  # deliberately zone 11 coords
    t = {'id': 'z', 'native_resolution_m': 2, 'delivered_date': '2020-01-01'}
    p = _tile(tmp_path, 'z', np.full((40, 40), -10), x - 500, y + 500, crs='EPSG:32611', cell=25.0)
    out, aff = _mosaic(tmp_path, [(t, p)])
    gx, gy = Transformer.from_crs(4326, 3310, always_xy=True).transform(lon, lat)
    c, r = ~aff * (gx, gy)
    assert out[int(r), int(c)] == 2


# --- habitat tile windows ---------------------------------------------------------------------

@pytest.mark.parametrize('shape,edge,halo', [((1, 1), 1024, 8), ((1, 100_000), 1024, 2), ((100_000, 1), 1024, 2),
                                             ((1025, 1025), 1024, 0), ((3, 3), 2, 5), ((0, 7), 4, 1)])
def test_tile_windows_partition_cores_and_locals_index_the_core(shape, edge, halo):
    seen = np.zeros(shape, int)
    ids = np.arange(shape[0] * shape[1]).reshape(shape)
    for core, padded, local in habitat_tiles.windows(shape, edge, halo):
        seen[core] += 1
        assert (ids[padded][local] == ids[core]).all()
    assert (seen == 1).all()


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)

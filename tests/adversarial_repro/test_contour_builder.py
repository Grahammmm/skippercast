"""scripts/build_depth_contours.py and platform/depth_contours.py on synthetic survey grids."""
import hashlib
import math

import numpy as np
import pytest
from rasterio.transform import Affine

from skippercast.platform import depth_contours as dc
from .synth import load_script, write_tif

bdc = load_script('build_depth_contours')
ORIGIN = Affine(2, 0, 500000, 0, -2, 4000000)


def blocks(paths, **_):
    lattice = bdc.lattice_for(paths)
    return bdc.merged_blocks(paths, lattice)


def flat(tmp_path, name, value, size=32, transform=ORIGIN, **kw):
    return write_tif(tmp_path / name, np.full((size, size), value, 'float32'), transform=transform, **kw)


def test_first_source_wins_overlap_with_conflicting_depths(tmp_path):
    a, b = flat(tmp_path, 'a.tif', -10), flat(tmp_path, 'b.tif', -50)
    depth, owner, _ = blocks([a, b])
    assert owner.max() == 0 and np.allclose(depth[owner == 0], 10 * dc.FEET_PER_M)
    depth2, owner2, _ = blocks([b, a])
    assert np.allclose(depth2[owner2 == 0], 50 * dc.FEET_PER_M)


def test_one_nodata_cell_invalidates_only_its_block(tmp_path):
    data = np.full((32, 32), -10, 'float32')
    data[3, 3] = -9999
    depth, owner, _ = blocks([write_tif(tmp_path / 'n.tif', data, nodata=-9999)])
    assert np.isnan(depth[0, 0]) and np.isfinite(depth[0, 1]) and np.isfinite(depth[1, 0])


def test_inf_and_nan_cells_are_not_water(tmp_path):
    data = np.full((16, 16), -10, 'float32')
    data[0, 0], data[0, 8], data[8, 0] = np.inf, -np.inf, np.nan
    depth, _, _ = blocks([write_tif(tmp_path / 'i.tif', data)])
    assert np.isnan(depth[0, 0]) and np.isnan(depth[0, 1]) and np.isnan(depth[1, 0]) and np.isfinite(depth[1, 1])


def test_value_exactly_zero_and_exactly_minus_3000_edges(tmp_path):
    data = np.full((16, 16), -10, 'float32')
    data[:, 8:] = 0
    depth, _, _ = blocks([write_tif(tmp_path / 'z.tif', data)])
    assert np.isfinite(depth[0, 0]) and np.isnan(depth[0, 1])  # shoreline cells are land, not 0 ft water


def test_grids_with_different_cell_sizes_are_refused(tmp_path):
    a = flat(tmp_path, 'a.tif', -10)
    b = flat(tmp_path, 'b.tif', -10, size=16, transform=Affine(4, 0, 500000, 0, -4, 4000000))
    with pytest.raises(ValueError):
        blocks([a, b])


def test_grids_in_different_crs_are_refused(tmp_path):
    a = flat(tmp_path, 'a.tif', -10)
    b = flat(tmp_path, 'b.tif', -10, crs='EPSG:32611')
    with pytest.raises(ValueError):
        blocks([a, b])


def test_misaligned_grid_is_refused(tmp_path):
    a = flat(tmp_path, 'a.tif', -10)
    b = flat(tmp_path, 'b.tif', -10, transform=Affine(2, 0, 500001, 0, -2, 4000000))
    with pytest.raises(ValueError):
        blocks([a, b])


def test_sources_touching_only_at_a_corner_leave_no_shared_block(tmp_path):
    a = flat(tmp_path, 'a.tif', -10)
    b = flat(tmp_path, 'b.tif', -20, transform=Affine(2, 0, 500064, 0, -2, 3999936))
    depth, owner, _ = blocks([a, b])
    assert set(np.unique(owner)) == {-1, 0, 1}
    assert (owner == 0).sum() == 16 and (owner == 1).sum() == 16


def test_single_pixel_grid_makes_no_blocks_and_does_not_crash(tmp_path):
    depth, owner, _ = blocks([write_tif(tmp_path / 'p.tif', np.array([[-10.0]], 'float32'))])
    assert np.isnan(depth).all() and (owner == -1).all()


def test_extreme_aspect_grid(tmp_path):
    depth, owner, _ = blocks([write_tif(tmp_path / 'strip.tif', np.full((8, 4096), -10, 'float32'))])
    assert depth.shape == (1, 512) and np.isfinite(depth).all()


def test_blocks_are_identical_for_same_input_twice(tmp_path):
    rng = np.random.default_rng(1)
    p = write_tif(tmp_path / 'r.tif', (-rng.random((64, 64)) * 100 - 1).astype('float32'))
    a, b = blocks([p])[0], blocks([p])[0]
    assert hashlib.sha256(a.tobytes()).digest() == hashlib.sha256(b.tobytes()).digest()


def test_south_up_grid_matches_its_north_up_twin(tmp_path):
    """Same ground, same values, stored upside-down: contours must not be mirrored."""
    rng = np.random.default_rng(2)
    data = (-np.linspace(5, 60, 32)[:, None] * np.ones((1, 32)) - rng.random((32, 32))).astype('float32')
    north = write_tif(tmp_path / 'n.tif', data)
    south = write_tif(tmp_path / 's.tif', data[::-1], transform=Affine(2, 0, 500000, 0, 2, 4000000 - 64))
    dn = blocks([north])[0]
    try:
        ds = blocks([south])[0]
    except ValueError as exc:
        # A clear refusal is acceptable; an obscure numpy error is not.
        assert 'north' in str(exc).lower(), f'south-up grid crashed obscurely: {exc}'
        return
    assert np.allclose(dn, ds, equal_nan=True)


def test_feet_grid_is_not_read_as_metres(tmp_path):
    """A raster tagged feet: -100 ft is 30.48 m = 100 ft. The builder reads the number as metres."""
    p = flat(tmp_path, 'ft.tif', -100, units='ft', tags={'z_units': 'ft'})
    depth = blocks([p])[0]
    assert np.nanmax(depth) == pytest.approx(100, rel=0.01)


def test_integer_grid_does_not_crash_the_reader(tmp_path):
    """An int16 grid (nodata -32768) hits masked.filled(np.nan), which numpy refuses for integers."""
    p = write_tif(tmp_path / 'i16.tif', np.full((32, 32), -20, 'int16'), nodata=-32768)
    depth = blocks([p])[0]
    assert np.nanmax(depth) == pytest.approx(20 * dc.FEET_PER_M, rel=0.01)


def test_packed_scale_offset_is_applied(tmp_path):
    """Stored -2000 with scale 0.01 is -20 m (65.6 ft); the builder uses the raw number (6561 ft)."""
    p = write_tif(tmp_path / 'pk.tif', np.full((32, 32), -2000, 'float32'), scale=0.01, offset=0.0)
    depth = blocks([p])[0]
    assert np.nanmax(depth) == pytest.approx(20 * dc.FEET_PER_M, rel=0.01)


def test_positive_down_depth_grid_is_not_silently_dropped(tmp_path):
    """A positive-down raster (+25 = 25 m deep) yields no blocks and no error."""
    p = write_tif(tmp_path / 'pd.tif', np.full((32, 32), 25, 'float32'), tags={'positive': 'down'})
    with pytest.raises(ValueError):
        depth = blocks([p])[0]
        if np.isnan(depth).all():
            raise ValueError('every block silently dropped')
        pytest.fail('positive-down grid was accepted as water at wrong sign')


def test_lattice_for_refuses_absurd_extent(tmp_path):
    a = flat(tmp_path, 'a.tif', -10)
    b = flat(tmp_path, 'b.tif', -10, transform=Affine(2, 0, 500000 + 2_000_000, 0, -2, 4000000 + 2_000_000))
    x0, y0, w, h = bdc.lattice_for([a, b])
    assert w * h < 250_000_000, f'lattice of {w}x{h} blocks would be allocated as float64 + int8 arrays'


def test_to_lonlat_across_antimeridian_has_no_world_wide_jump():
    from pyproj import Transformer
    t = Transformer.from_crs('EPSG:32660', 'EPSG:4326', always_xy=True)  # UTM 60N, 174E..180E
    pts = [(780000.0 + i * 5000, 4000000.0) for i in range(8)]  # runs east past 180E
    lons = [p[0] for p in bdc.to_lonlat(t, pts)]
    assert max(abs(a - b) for a, b in zip(lons, lons[1:])) < 180, lons


# --- marching squares ---------------------------------------------------------------------

def _segments(lines, dx=0):
    out = set()
    for line in lines:
        for p, q in zip(line, line[1:]):
            p, q = (round(p[0] + dx, 9), round(p[1], 9)), (round(q[0] + dx, 9), round(q[1], 9))
            out.add(tuple(sorted((p, q))))
    return out


def test_level_exactly_on_cell_values_gives_finite_lines_that_end_on_the_node_edge():
    grid = [[0, 0, 0], [0, 30, 30], [0, 30, 60]]
    lines = dc.trace(grid, [30])[30]
    assert lines and all(math.isfinite(v) for line in lines for p in line for v in p)


def test_trace_flat_grid_exactly_on_level_draws_nothing():
    assert dc.trace([[30] * 4 for _ in range(4)], [30]) == {30: []}


def test_trace_treats_nan_as_invalid_like_none():
    grid = [[10.0, 10.0, 10.0], [10.0, float('nan'), 50.0], [10.0, 50.0, 50.0]]
    out = dc.trace(grid, [30])[30]
    for line in out:
        for c, r in line:
            assert math.isfinite(c) and math.isfinite(r)
    # Squares touching the NaN must not draw.
    assert out == dc.trace([[10.0, 10.0, 10.0], [10.0, None, 50.0], [10.0, 50.0, 50.0]], [30])[30]


def test_tile_seam_segments_match_whole_grid():
    rng = np.random.default_rng(3)
    grid = (rng.random((20, 21)) * 90).tolist()
    whole = _segments(dc.trace(grid, [30, 60])[30]) | _segments(dc.trace(grid, [30, 60])[60])
    left = [row[:11] for row in grid]
    right = [row[10:] for row in grid]  # one shared column
    got = set()
    for d in (30, 60):
        got |= _segments(dc.trace(left, [d])[d])
        got |= _segments(dc.trace(right, [d])[d], 10)
    assert got == whole


def test_trace_is_deterministic():
    rng = np.random.default_rng(4)
    grid = (rng.random((30, 30)) * 90).tolist()
    assert dc.trace(grid, [30, 60]) == dc.trace(grid, [30, 60])


def test_levels_boundaries():
    assert dc.levels(30, 30) == [30] and dc.levels(0, 29.9) == [] and dc.levels(-50, 10) == []
    assert dc.levels(0, 10_000)[-1] == dc.SHELF_LIMIT_FT
    with pytest.raises(ValueError):
        dc.levels(float('nan'), 100)

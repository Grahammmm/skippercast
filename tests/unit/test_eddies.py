import math
import struct

import pytest

from skippercast.pipeline.eddies import EddyGridError, eddies_for

_FRAME = 1_790_042_400


def _vortex(*, latitude: float = 38, scale_km: float = 35, spin: float = 1, longitude: float = -123):
    lats = [latitude + i * 0.04 for i in range(-30, 31)]
    lons = [-123 + i * 0.04 for i in range(-35, 36)]
    u, v = [], []
    for lat in lats:
        y = (lat - latitude) * 111_195
        ur, vr = [], []
        for lon in lons:
            x = (lon - longitude) * 111_195 * math.cos(math.radians(latitude))
            rate = spin * 1e-5 * math.exp(-(x*x + y*y) / (2 * (scale_km * 1000)**2))
            ur.append(-rate * y)
            vr.append(rate * x)
        u.append(ur)
        v.append(vr)
    return lats, lons, u, v


def _float32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


@pytest.mark.parametrize(("latitude", "spin", "reverse", "sense"), [
    (38, 1, None, "ccw"), (60, -1, "lat", "cw"), (38, 1, "lon", "ccw"),
])
def test_gaussian_vortex_has_physical_size_and_rotation(latitude, spin, reverse, sense):
    # A degree-based derivative, swapped axis, or unsigned spacing changes W or the sense.
    lats, lons, u, v = _vortex(latitude=latitude, spin=spin)
    if reverse == "lat":
        lats, u, v = lats[::-1], u[::-1], v[::-1]
    if reverse == "lon":
        lons, u, v = lons[::-1], [row[::-1] for row in u], [row[::-1] for row in v]
    # WCOFS degree axes are allowed to have float32 quantization noise.
    lats, lons = list(map(_float32, lats)), list(map(_float32, lons))
    eddy, = eddies_for(lats, lons, u, v, _FRAME)
    assert set(eddy) == {"outline", "sense", "diameter_km", "ow_min"}
    assert eddy["sense"] == sense
    # Analytically W crosses zero at one Gaussian scale and reaches -4*A² at
    # the centre. Allow 20% for the negative cutoff and finite grid resolution.
    assert eddy["diameter_km"] == pytest.approx(70, rel=0.20)
    assert eddy["ow_min"] == pytest.approx(-4e-10, rel=0.03)
    ring = eddy["outline"]
    assert ring[0] == ring[-1]
    assert len({tuple(point) for point in ring[:-1]}) == len(ring) - 1
    assert min(x for x, _ in ring) < -123 < max(x for x, _ in ring)
    assert min(y for _, y in ring) < latitude < max(y for _, y in ring)
    assert all((x0 == x1) != (y0 == y1) for (x0, y0), (x1, y1) in zip(ring, ring[1:]))


@pytest.mark.parametrize("flow", ["uniform", "simple shear", "pure strain", "all missing"])
def test_no_rotation_dominated_core(flow):
    # Strain and simple shear must not become eddies just because velocities vary.
    lats, lons = list(range(30, 40)), list(range(-130, -120))
    u = [[{"uniform": 0.5, "simple shear": j * j, "pure strain": i + j,
           "all missing": None}[flow] for j in range(len(lons))] for i in range(len(lats))]
    v = [[i + j if flow == "pure strain" else -0.25 for j in range(len(lons))]
         for i in range(len(lats))]
    assert eddies_for(lats, lons, u, v, _FRAME) == []


def test_sub_four_cell_vortex_is_not_resolved():
    # Strong vorticity alone must not promote a subgrid-sized feature.
    assert eddies_for(*_vortex(scale_km=5), _FRAME) == []


def test_frame_threshold_excludes_weak_rotation_with_a_stronger_core():
    # A W < 0 cutoff alone keeps both vortices; the frame-relative cutoff does not.
    lats, lons, u, v = _vortex(scale_km=20, longitude=-123.7)
    _, _, weak_u, weak_v = _vortex(scale_km=20, longitude=-122.3, spin=0.05)
    assert len(eddies_for(lats, lons, weak_u, weak_v, _FRAME)) == 1
    combined_u = [[a + b for a, b in zip(ur, wr)] for ur, wr in zip(u, weak_u)]
    combined_v = [[a + b for a, b in zip(vr, wr)] for vr, wr in zip(v, weak_v)]
    strong, = eddies_for(lats, lons, combined_u, combined_v, _FRAME)
    assert max(lon for lon, _ in strong["outline"]) < -123


@pytest.mark.parametrize("edge", ["north", "south", "east", "west"])
def test_core_cut_off_by_subset_is_dropped(edge):
    lats, lons, u, v = _vortex()
    # Clip inside a detected core; tracing cell edges alone would close the fragment.
    assert len(eddies_for(lats, lons, u, v, _FRAME)) == 1
    ys = {"north": slice(None, 34), "south": slice(27, None)}.get(edge, slice(None))
    xs = {"east": slice(None, 39), "west": slice(32, None)}.get(edge, slice(None))
    assert eddies_for(lats[ys], lons[xs], [r[xs] for r in u[ys]], [r[xs] for r in v[ys]], _FRAME) == []


@pytest.mark.parametrize(("component", "missing"), [("u", None), ("v", math.nan), ("v", math.inf)])
def test_mask_slit_splits_core_and_invalidates_adjacent_stencils(component, missing):
    # Applying the mask after differentiation or bridging it geometrically would
    # leave one outline (or let one of the outlines use the adjacent cells).
    lats, lons, u, v = _vortex(scale_km=45)
    slit = len(lons) // 2
    assert len(eddies_for(lats, lons, u, v, _FRAME)) == 1
    grid = u if component == "u" else v
    for row in grid:
        row[slit] = missing
    west, east = sorted(eddies_for(lats, lons, u, v, _FRAME),
                        key=lambda eddy: min(x for x, _ in eddy["outline"]))
    assert max(x for x, _ in west["outline"]) == (lons[slit - 2] + lons[slit - 1]) / 2
    assert min(x for x, _ in east["outline"]) == (lons[slit + 1] + lons[slit + 2]) / 2


def test_mask_hole_is_not_filled_by_a_single_outer_outline():
    # An outer perimeter alone would enclose water where no derivatives are known.
    lats, lons, u, v = _vortex()
    assert len(eddies_for(lats, lons, u, v, _FRAME)) == 1
    v[len(lats) // 2][len(lons) // 2] = None
    assert eddies_for(lats, lons, u, v, _FRAME) == []


@pytest.mark.parametrize(("index", "invalid"), [
    (0, []), (0, [1, 2]), (0, [1, 1, 1]), (0, [1, 2, 1]), (0, [1, 2, 4]),
    (0, [1, 2, math.nan]), (0, [[1], [2], [3]]), (0, [90, 91, 92]),
    (1, [-179, 180, 179]), (1, [-183, -182, -181]), (1, [1, 2, math.inf]),
    (1, "123"), (2, None), (2, [0] * 9), (2, [[0, 0, 0]] * 2),
    (2, [[0, 0, 0], [0, 0], [0, 0, 0]]), (3, [[0, 0, 0]] * 4),
    (3, [[0, 0]] * 3), (3, [[0, 0, 0], [0, 0, "0"], [0, 0, 0]]),
    (3, [[True, 0, 0]] * 3),
])
def test_bad_axes_or_grid_raise_named_error(index, invalid):
    # Wrong shapes must be rejected before stencil indexing, not truncated by zip.
    args = [[37, 38, 39], [-123, -122, -121], [[0] * 3] * 3, [[0] * 3] * 3]
    args[index] = invalid
    with pytest.raises(EddyGridError):
        eddies_for(args[0], args[1], args[2], args[3], _FRAME)

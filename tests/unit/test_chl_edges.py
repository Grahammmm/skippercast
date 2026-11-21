from datetime import datetime, timezone
import math

import pytest

from skippercast.pipeline.chl_edges import ChlEdgeError, edges_for


WHEN = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
RES = 0.04


def _field(profile, length=12, *, across_lat=False, omit=lambda i, j: False):
    return [(round(36 + (j if across_lat else i) * RES, 5),
             round(-123 + (i if across_lat else j) * RES, 5), chl)
            for i in range(length) for j, chl in enumerate(profile) if not omit(i, j)]


@pytest.mark.parametrize("across_lat", [False, True])
@pytest.mark.parametrize("profile", [(1, 1, 10, 10), (10, 10, 1, 1)])
def test_step_has_one_thinned_edge_with_grid_uncertainty(across_lat, profile):
    # A central-difference step lights up two cells; retain a single ridge
    # independent of sign and axis, with observed coordinate order and time.
    rows = _field(profile, length=5, across_lat=across_lat)
    edge, = edges_for(reversed(rows + rows[:1]), RES, WHEN)
    expected = [[lon, lat] for lat, lon, _ in rows[1::4]]
    assert edge["geometry"] == {"type": "LineString", "coordinates": expected}
    assert edge["cells"] == 5
    assert edge["observed_at"] == "2026-11-18T12:00:00Z"
    assert edge["strength_log10_per_cell"] == pytest.approx(0.5)
    factor = 1 if across_lat else sum(math.cos(math.radians(lat)) for _, lat in expected) / 5
    assert edge["band_half_width_km"] == pytest.approx(2.2239 * factor)


@pytest.mark.parametrize("high, count", [(1, 0), (10**0.59, 0), (10**0.6, 1), (10**0.61, 1)])
def test_threshold_is_log_change_per_cell_over_two_steps(high, count):
    # A linear or unnormalised difference would accept the sub-threshold case.
    for scale in (1, 10):
        assert len(edges_for(_field([scale, scale, high * scale]), RES, WHEN)) == count


def test_subthreshold_noise_has_no_edge():
    # Small multiplicative noise is not a colour break even where it forms a ridge.
    rows = [(lat, lon, 1 + ((i * 17) % 11 - 5) * 0.02)
            for i, (lat, lon, _) in enumerate(_field([1] * 8))]
    assert edges_for(rows, RES, WHEN) == []


@pytest.mark.parametrize("missing", [0, 1, 2, None])
@pytest.mark.parametrize("across_lat", [False, True])
def test_cloud_gap_splits_observed_chain(across_lat, missing):
    # A missing ridge cell, either stencil endpoint, or a whole transect
    # must split even a one-cell gap. Both fragments meet the five-cell floor.
    rows = _field([1, 1, 10], length=11, across_lat=across_lat,
                  omit=lambda i, j: i == 5 and (missing is None or j == missing))
    features = edges_for(rows, RES, WHEN)
    assert [feature["cells"] for feature in features] == [5, 5]
    axis = 0 if across_lat else 1
    start = -123 if across_lat else 36
    assert [[coord[axis] for coord in feature["geometry"]["coordinates"]] for feature in features] == [
        [round(start + i * RES, 5) for i in range(5)],
        [round(start + i * RES, 5) for i in range(6, 11)],
    ]


def test_diagonal_does_not_cut_across_an_unobserved_corner():
    # Two 5-cell ridges meet diagonally, but one corner between their ends
    # is cloudy. Eight-neighbour stitching alone would join them into one.
    horizontal = [(y, x, 10 if y == 5 else 1) for y in range(3, 6) for x in range(-3, 2)]
    vertical = [(y, x, 1 if x == 3 else 10) for y in range(5, 10) for x in range(1, 4)]
    rows = [(36 + y * RES, -123 + x * RES, chl) for y, x, chl in set(horizontal + vertical)]
    assert [feature["cells"] for feature in edges_for(rows, RES, WHEN)] == [5, 5]


def test_minimum_applies_to_each_fragment():
    # Pooling all detected cells could incorrectly keep two short fragments.
    rows = _field([1, 1, 10], length=9, omit=lambda i, j: i == 4)
    assert edges_for(rows, RES, WHEN) == []
    assert edges_for([], RES, WHEN) == []


@pytest.mark.parametrize("chl", [0, -1, math.nan, math.inf, -math.inf, None, False, "1"])
def test_invalid_chlorophyll_is_not_silently_masked(chl):
    # Unusable measurements are errors, not implicitly omitted cloud cells.
    with pytest.raises(ChlEdgeError, match="chlorophyll"):
        edges_for([(36, -123, chl)], RES, WHEN)


@pytest.mark.parametrize("lat, lon", [(math.nan, -123), (36, math.inf), (91, -123),
                                      (36, -181), (True, -123), (36, "-123")])
def test_invalid_coordinates_raise_even_without_enough_cells(lat, lon):
    with pytest.raises(ChlEdgeError, match="latitude|longitude"):
        edges_for([(lat, lon, 1)], RES, WHEN)


@pytest.mark.parametrize("dy, dx", [(0.00002, 0), (0, -0.00002), (RES / 2, 0), (0, RES / 2)])
def test_off_lattice_cells_are_not_rounded_onto_a_neighbour(dy, dx):
    rows = _field([1, 1, 10])
    lat, lon, chl = rows[16]
    rows[16] = (lat + dy, lon + dx, chl)
    with pytest.raises(ChlEdgeError, match="off the tile lattice"):
        edges_for(rows, RES, WHEN)


def test_five_decimal_coordinates_on_nondecimal_spacing_keep_observed_positions():
    # A strict zero-tolerance address check would reject this valid tile.
    res = 1 / 24
    rows = [(round(36.000005 + i * res, 5), round(-123 + j * res, 5), chl)
            for i in range(5) for j, chl in enumerate([1, 1, 10])]
    edge, = edges_for(rows, res, WHEN)
    assert edge["geometry"]["coordinates"] == [[lon, lat] for lat, lon, _ in rows[1::3]]


def test_conflicting_overlaps_do_not_pick_a_value():
    rows = _field([1, 1, 10])
    lat, lon, chl = rows[0]
    with pytest.raises(ChlEdgeError, match="conflicting overlapping"):
        edges_for(rows + [(lat, lon, chl * 2)], RES, WHEN)

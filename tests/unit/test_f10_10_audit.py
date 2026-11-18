"""F10-10 / SCA-284: a cell off the tile lattice is refused, not snapped to a neighbouring address.

Contract protected: `_grid` pools cells onto one lattice; rounding to the nearest address used to make a cell
displaced by 40% of a cell look like a nominal neighbour, so the gradient used a shorter distance than the
source coordinates support. Believable bug: replacing the residual check by plain `round()` makes the
negative control below yield a front again; rejecting every float residual makes the positive control fail.
"""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from skippercast.pipeline.sst_fronts import SstFrontError, publish

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
HEALTH = {"feeds": {"sst-fronts": {"max_age_hours": 48}}}
FIELDS = ["latitude", "longitude", "temperature_c", "analysis_error_c"]
RES = 0.01


def tile(offset=0.0, rows=range(7), moved=None):
    """Seven rows x 12 columns with a 14 -> 16 C step at column 6; `moved` is {(i, j): (dlat, dlon)} in cells."""
    moved = moved or {}
    cells = []
    for i in rows:
        for j in range(12):
            di, dj = moved.get((i, j), (0, 0))
            cells.append([round(35 + offset + (i + di) * RES, 5), round(-121 + offset + (j + dj) * RES, 5),
                          14.0 if j < 6 else 16.0, 0.4])
    return {"fields": FIELDS, "resolution_degrees": [RES, RES],
            "frames": [{"time": NOW.timestamp() - 6 * 3600, "cells": cells}]}


def fronts(*tiles):
    return publish("test-coast", [(f"t{n}", t) for n, t in enumerate(tiles)], HEALTH, NOW)


def test_control_aligned_seven_row_tile_yields_a_front():
    assert len(fronts(tile())["fronts"]) == 1


@pytest.mark.parametrize("moved", [
    {(3, 5): (0.4, 0.0)},  # a middle cell displaced 40% of a cell north
    {(3, 5): (0.0, 0.4)},  # ... or east
    {(3, 5): (-0.4, -0.4)},
    {(6, 11): (0.4, 0.0)},  # the far corner
    {(0, 0): (0.0, 0.4)},  # the cell that would otherwise define the origin
])
def test_a_cell_displaced_by_forty_percent_is_refused(moved):
    with pytest.raises(SstFrontError, match="off the tile lattice"):
        fronts(tile(moved=moved))


def test_displaced_cell_in_a_second_tile_is_refused():
    whole = tile()
    first, second = deepcopy(whole), deepcopy(whole)
    first["frames"][0]["cells"] = whole["frames"][0]["cells"][:42]
    second["frames"][0]["cells"] = tile(moved={(5, 6): (0.4, 0.0)})["frames"][0]["cells"][42:]
    assert len(fronts(first, tile())["fronts"]) == 1
    with pytest.raises(SstFrontError, match="off the tile lattice"):
        fronts(first, second)


@pytest.mark.parametrize("offset", [0.0, 0.003, 0.00123457])
def test_five_decimal_rounding_of_aligned_cells_keeps_the_same_front(offset):
    # Tile coordinates are rounded to 5 decimals (tile() does it); an off-grid origin rounds each cell differently.
    got = fronts(tile(offset))["fronts"]
    assert len(got) == 1
    assert got[0]["cells"] == 7
    assert got[0]["strength_c_per_km"] == fronts(tile())["fronts"][0]["strength_c_per_km"]


def test_identical_overlap_is_unchanged():
    doubled = tile()
    doubled["frames"][0]["cells"] *= 2
    assert fronts(doubled) == fronts(tile())

"""RF0844-6: native grid origins, coordinates, holes and true overlaps."""

from copy import deepcopy
import json

import pytest

from skippercast.pipeline.sst_fronts import SstFrontError, publish_region
from tests.gis.test_sst_fronts import HEALTH, NOW, at, fronts


def shifted(res=0.01, offset=0.005, rows=range(12), cols=range(12)):
    return {
        "fields": ["latitude", "longitude", "temperature_c", "analysis_error_c"],
        "resolution_degrees": [res, res],
        "frames": [{"time": at(6), "cells": [
            [round(35 + offset + i * res, 5), round(-121 + offset + j * res, 5),
             14.0 if j < 6 else 16.0, 0.4] for i in rows for j in cols
        ]}],
    }


@pytest.mark.parametrize("res,offset", [(0.01, 0.005), (0.05, 0.025)])
def test_half_offset_grids_keep_distinct_cells(res, offset):
    doc = fronts(shifted(res, offset))
    assert len(doc["fronts"]) == 1
    edge = doc["fronts"][0]
    assert edge["cells"] == 12
    assert edge["geometry"] == {"type": "LineString", "coordinates": [
        [round(-121 + offset + 5 * res, 5), round(35 + offset + i * res, 5)]
        for i in range(12)
    ]}


def test_offset_geometry_uses_native_centers():
    # Non-half offsets also used to be silently snapped to a zero-origin lattice.
    tile = shifted(offset=0.003)
    coordinates = fronts(tile)["fronts"][0]["geometry"]["coordinates"]
    assert coordinates == [[-120.947, round(35.003 + i * 0.01, 5)] for i in range(12)]
    centers = {(c[1], c[0]) for c in tile["frames"][0]["cells"]}
    assert all(tuple(c) in centers for c in coordinates)


@pytest.mark.parametrize("res,offset", [(0.01, 0.005), (0.05, 0.025)])
def test_shifted_grid_split_tiles_and_order_are_identical(res, offset):
    whole = shifted(res, offset)
    control = fronts(whole)
    for axis in ("rows", "cols"):
        first = shifted(res, offset, **{axis: range(6)})
        second = shifted(res, offset, **{axis: range(6, 12)})
        assert fronts(first, second) == control
        for tile in (first, second):
            tile["frames"][0]["cells"].reverse()
        assert fronts(second, first, first) == control
    doubled = deepcopy(whole)
    doubled["frames"][0]["cells"] *= 2
    assert fronts(doubled) == control


def test_offset_grid_holes_are_not_bridged():
    # Two four-cell ridges must not be compacted into one eight-cell front.
    assert fronts(shifted(rows=[0, 1, 2, 3, 8, 9, 10, 11]))["fronts"] == []
    # Without the two neighbors across the thermal edge there is no support.
    assert fronts(shifted(cols=[0, 1, 2, 3, 4, 7, 8, 9, 10, 11]))["fronts"] == []
    for value in (15.0, None):
        tile = shifted()
        for cell in tile["frames"][0]["cells"]:
            cell[2] = value
        assert fronts(tile)["fronts"] == []
    assert fronts(shifted(rows=[]))["fronts"] == []
    # Missing-value rows cannot choose the native origin.
    tile = shifted()
    tile["frames"][0]["cells"].insert(0, [None, None, None, None])
    assert fronts(tile) == fronts(shifted())


@pytest.mark.parametrize("field,value", [(2, 15.0), (3, 0.5), (0, 35.006), (1, -120.994)])
def test_shifted_conflict_refuses_and_preserves_previous_output(tmp_path, field, value):
    good = shifted()
    changed = deepcopy(good)
    changed["frames"][0]["cells"][0][field] = value
    tiles = tmp_path / "habitat-tiles"
    tiles.mkdir()
    health = tmp_path / "feed-health.json"
    health.write_text(json.dumps(HEALTH))
    output = tmp_path / "sst-fronts.json"
    previous = b'{"sentinel":"previous output"}\n'
    output.write_bytes(previous)
    for order in ((good, changed), (changed, good)):
        with pytest.raises(SstFrontError, match="conflicting overlapping measurements"):
            fronts(*order)
        for name, tile in zip(("a", "b"), order):
            (tiles / f"sst-analysis-{name}.json").write_text(json.dumps(tile))
        with pytest.raises(SstFrontError, match="conflicting overlapping measurements"):
            publish_region(tmp_path, health, NOW)
        assert output.read_bytes() == previous

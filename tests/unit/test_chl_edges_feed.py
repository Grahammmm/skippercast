from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from skippercast.pipeline.chl_edges import ChlEdgeError
from skippercast.pipeline.chl_edges_feed import (
    ChlEdgeFeedError,
    MIN_OBSERVED_FRACTION,
    publish,
    usable_chl_frames,
)


NOW = datetime.fromisoformat("2026-11-18T14:00:00.250+01:00")
WHEN = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
EPOCH = int(WHEN.timestamp())
OBSERVED = "2026-11-18T12:00:00Z"
STEP = 0.25
FIELDS = ["latitude", "longitude", "chlorophyll_mg_m3"]
NO_REFUSALS = {"missing_time": 0, "unparseable_time": 0, "future": 0, "stale": 0}


def _tile(cells, *, time: int | str = EPOCH):
    return {"fields": FIELDS, "resolution_degrees": [STEP, STEP],
            "frames": [{"time": time, "cells": cells, "valid_cells": len(cells)}]}


def _step_field(columns):
    return [[lat, -124 + column * STEP, chl]
            for column in columns for lat, chl in [(36, 1), (36.25, 1), (36.5, 10)]]


def _edge():
    return {"id": "edge-1", "observed_at": OBSERVED, "cells": 5, "strength_log10_per_cell": 0.5,
            "band_half_width_km": STEP * 111.195 / 2,
            "geometry": {"type": "LineString", "coordinates": [
                [-124, 36.25], [-123.75, 36.25], [-123.5, 36.25], [-123.25, 36.25], [-123, 36.25]]}}


def _publish(tiles, meta, age: float = 24):
    return publish("test-region", tiles, meta, NOW, age, "Test satellite", "Test credit")


def _expected(*, observed_at: str | None = OBSERVED, fraction=None, withheld=None, refused=None, edges=None,
              age: float = 24):
    return {
        "schema_version": 1,
        "region_id": "test-region",
        "layer_id": "chl-edges",
        "product": "Test satellite",
        "credit": "Test credit",
        "generated_at": "2026-11-18T13:00:00Z",
        "max_age_hours": age,
        "observed_at": observed_at,
        "observed_fraction": fraction,
        "withheld": withheld,
        "refused_frames": NO_REFUSALS if refused is None else refused,
        "edges": [] if edges is None else edges,
    }


def test_c1_provisional_floor():
    """C1: Keep the 20% provisional coverage floor from drifting."""
    assert MIN_OBSERVED_FRACTION == 0.2


def test_c2_frame_selection_and_projection():
    """C2: Catch misclassified times, an exclusive cutoff, and fixed-index or reordered rows."""
    boundary = NOW.astimezone(timezone.utc) - timedelta(hours=24)
    tile = _tile([])
    tile["fields"] = ["chlorophyll_mg_m3", "unused", "longitude", "latitude"]
    tile["frames"] = [
        None, {}, {"time": None},
        {"time": "bad"}, {"time": "2026-11-18T12:00:00"}, {"time": True},
        {"time": NOW + timedelta(seconds=1)},  # a datetime object is not a wire timestamp
        {"time": (NOW + timedelta(seconds=1)).isoformat()},
        {"time": (boundary - timedelta(microseconds=1)).isoformat()},
        {"time": boundary.isoformat(), "cells": [[10, 0, -123, 37], [None, 0, -124, 36], [2, 0, -125, 35]]},
        {"time": EPOCH, "cells": [[None, 0, -124, 36]]},
    ]
    assert usable_chl_frames(iter([("west", tile)]), NOW, 24) == (
        [(boundary, [[37, -123, 10], [35, -125, 2]], STEP), (WHEN, [], STEP)],
        {"missing_time": 3, "unparseable_time": 4, "future": 1, "stale": 1},
    )


@pytest.mark.parametrize("tile", [
    None,
    _tile([]) | {"fields": "latitude longitude chlorophyll_mg_m3"},
    *(_tile([]) | {"fields": [field for field in FIELDS if field != missing]} for missing in FIELDS),
    _tile([]) | {"frames": None},
    *(_tile([]) | {"resolution_degrees": resolution} for resolution in [
        None, [STEP], [STEP, STEP, STEP], [STEP, 0.125], ["0.25", "0.25"], [True, True],
        [0, 0], [-0.25, -0.25], [0.5, 0.5], [float("inf"), float("inf")],
    ]),
])
def test_c2_malformed_tiles_name_the_tile(tile):
    """C2: Reject bad layouts even before a frame's time can be considered."""
    with pytest.raises(ChlEdgeFeedError, match="^west:") as exc:
        usable_chl_frames([("west", tile)], NOW, 24)
    assert exc.type is ChlEdgeFeedError


@pytest.mark.parametrize("cells", [None, {"latitude": 36}, ["not a list"], [[36, -124]]])
def test_c2_malformed_cells_raise(cells):
    """C2: A malformed fresh frame must not become a clear frame with fewer rows."""
    tile = _tile([])
    tile["frames"][0]["cells"] = cells
    with pytest.raises(ChlEdgeFeedError, match="^west frame 0:") as exc:
        usable_chl_frames([("west", tile)], NOW, 24)
    assert exc.type is ChlEdgeFeedError


@pytest.mark.parametrize("total, fraction, withheld", [
    pytest.param(47, 0.319, None, id="rounded-regional-fraction"),
    pytest.param(76, 0.197, "too-little-clear-water", id="cloud-withholds-real-edge"),
    pytest.param(75, 0.2, None, id="exact-floor-is-clear"),
    pytest.param(0, None, None, id="zero-total-is-unknown"),
    pytest.param(-1, None, None, id="negative-total-is-unknown"),
    pytest.param(76.0, None, None, id="float-total-is-unknown"),
    pytest.param(True, None, None, id="bool-total-is-unknown"),
    pytest.param(None, None, None, id="no-matching-time"),
])
def test_c3_pool_newest_and_apply_regional_coverage(total, fraction, withheld):
    """C3: Separate tile detection loses this edge; a tile-local denominator lets it through cloud."""
    older = EPOCH - 7200
    west = _tile(_step_field(range(2)), time="2026-11-18T04:00:00-08:00")
    east = _tile(_step_field(range(2, 5)))
    # A valid, older tile conflicts with the new readings if indiscriminately pooled.
    prior = _tile([[36, -124, 10]], time=older) | {"resolution_degrees": [0.125, 0.125]}
    tiles = iter([("west", west), ("east", east), ("old", prior)])
    meta = [{"time": older, "valid_cells": 1, "total_cells": 100}]
    if total is not None:
        meta.append({"time": EPOCH, "valid_cells": 15, "total_cells": total})
    assert _publish(tiles, meta) == _expected(
        fraction=fraction, withheld=withheld, edges=[] if withheld else [_edge()],
    )


def test_c3_no_usable_frame():
    """C3: Old data and manifest metadata alone must not create an observation."""
    older = EPOCH - 48 * 3600
    tile = _tile([], time=older)
    tile["frames"].extend([{}, {"time": "bad"}, {"time": "2026-11-18T14:00:00Z"}])
    assert _publish([("west", tile)], [{"time": older, "valid_cells": 0, "total_cells": 100}]) == _expected(
        observed_at=None, withheld="no-usable-frame",
        refused={"missing_time": 1, "unparseable_time": 1, "future": 1, "stale": 1},
    )


def test_c3_refuse_inconsistent_resolution_even_with_cloud():
    """C3: Withholding cannot conceal disagreement about the pooled grid."""
    tiles = [("west", _tile([])), ("east", _tile([]) | {"resolution_degrees": [0.125, 0.125]})]
    with pytest.raises(ChlEdgeFeedError, match="disagree on grid resolution") as exc:
        _publish(tiles, [{"time": EPOCH, "valid_cells": 0, "total_cells": 100}])
    assert exc.type is ChlEdgeFeedError


@pytest.mark.parametrize("meta", [None, {}, ()])
def test_c4_refuse_non_list_meta(meta):
    """C4: Bad manifest shape is an error, not a missing observation."""
    with pytest.raises(ChlEdgeFeedError) as exc:
        _publish([], meta)
    assert exc.type is ChlEdgeFeedError


@pytest.mark.parametrize("age", [True, False, "24", None, 0, -1, float("inf"), float("-inf"), float("nan")])
def test_c4_refuse_invalid_age(age):
    """C4: Invalid age must fail even without tiles; NaN must not disable the stale check."""
    with pytest.raises(ChlEdgeFeedError) as exc:
        _publish([], [], age)
    assert exc.type is ChlEdgeFeedError


def test_c4_detector_error_is_not_wrapped_or_dropped():
    """C4: Invalid measured chlorophyll remains a detector error, not a gap."""
    with pytest.raises(ChlEdgeError, match="^chlorophyll must be positive$") as exc:
        _publish([("west", _tile([[36, -124, 0]]))], [])
    assert exc.type is ChlEdgeError


def test_c4_document_build_performs_no_io():
    """C4: Catch accidental file, catalog or network access while building the document."""
    tiles = [("west", _tile(_step_field(range(5))))]
    with (patch("builtins.open", side_effect=AssertionError("file access")),
          patch("io.open", side_effect=AssertionError("path access")),
          patch("socket.socket", side_effect=AssertionError("network access"))):
        assert _publish(tiles, [], 1.5) == _expected(edges=[_edge()], age=1.5)

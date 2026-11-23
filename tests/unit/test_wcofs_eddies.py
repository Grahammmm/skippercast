"""Offline contracts for turning WCOFS surface frames into eddy tiles."""

from datetime import datetime, timezone
import math

import pytest

from skippercast.pipeline import wcofs_eddies
from skippercast.pipeline.eddies import EddyGridError
from skippercast.pipeline.eddies_tile import EddyTileError
from skippercast.pipeline.wcofs_eddies import WcofsEddiesError, eddy_tiles

_EARLY = 1767225600
_LATE = _EARLY + 10800


def _layer(*frames: dict) -> dict:
    return {
        "fields": ["latitude", "longitude", "temperature_c", "u_mps", "v_mps",
                   "temperature_gradient_c_per_km"],
        "resolution_degrees": [0.04, 0.04],
        "frames": list(frames),
    }


@pytest.mark.parametrize("fields", [
    None, "latitude longitude u_mps v_mps", [],
    ["longitude", "latitude", "u_mps", "v_mps"],
    ["temperature_c", "latitude", "longitude", "u_mps", "v_mps"],
    ["latitude", "longitude", "u_mps"], ["latitude", "longitude", "v_mps"],
])
def test_c1_rejects_missing_or_misplaced_fields(fields):
    """C1: Indexing by name still requires both velocities and the coordinate prefix."""
    layer = _layer()
    if fields is None:
        del layer["fields"]
    else:
        layer["fields"] = fields
    with pytest.raises(WcofsEddiesError) as caught:
        eddy_tiles(layer)
    assert type(caught.value) is WcofsEddiesError


@pytest.mark.parametrize("resolution", [
    None, 0.04, "04", {0: 0.04, 1: 0.04}, [], [0.04], [0.04, 0.04, 0.04],
    [0, 0.04], [0.04, -0.04], [math.nan, 0.04], [0.04, math.inf],
    [0.04, True], ["0.04", 0.04], [0.04, 10**400],
])
def test_c1_rejects_invalid_resolution(resolution):
    """C1: Catch coerced non-numbers, non-finite or nonpositive steps, and bad arity."""
    layer = _layer()
    if resolution is None:
        del layer["resolution_degrees"]
    else:
        layer["resolution_degrees"] = resolution
    with pytest.raises(WcofsEddiesError) as caught:
        eddy_tiles(layer)
    assert type(caught.value) is WcofsEddiesError


def test_c2_snaps_inclusive_limits_and_preserves_velocity_gaps(monkeypatch):
    """C2: Catch swapped steps, cropped axes or filled land gaps; C1: named columns."""
    # Last latitude falls short of its grid point; last longitude goes beyond it.
    # Their 1% edges must be included on both axes despite float representation.
    frame = {"time": _EARLY, "cells": [
        [38.08 - 0.0004, -123, 20, -6, 5],
        [38.04, -122.84, 20, None, 4],
        [38, -122.76 + 0.0008, 20, 3, -2],
        [38.04, -122.92, 20, 2, None],
        [38, -123, 20, -1, 1],
    ]}
    layer = _layer(frame)
    layer["fields"] = ["latitude", "longitude", "temperature_c", "v_mps", "u_mps"]
    layer["resolution_degrees"] = [0.04, 0.08]
    observed = []

    def detect(lats, lons, u, v, frame_time):
        observed.append((lats, lons, u, v, frame_time, frame_time.tzinfo))
        return []

    monkeypatch.setattr(wcofs_eddies, "eddies_for", detect)
    result = eddy_tiles(layer)
    assert result == [{"time": _EARLY, "tile": {"frame_time": "2026-01-01T00:00:00Z", "features": []},
                       "eddies": 0}]
    assert observed == [(
        [38, 38.04, 38.08], [-123, -122.92, -122.84, -122.76],
        [[1, None, None, -2], [None, None, None, None], [5, None, None, None]],
        [[-1, None, None, 3], [None, None, None, None], [-6, None, None, None]],
        datetime(2026, 1, 1, tzinfo=timezone.utc), timezone.utc,
    )]


@pytest.mark.parametrize("cell", [
    [38.04 + 0.000401, -123.0, 20, 0, 0],
    [38.0, -122.96 - 0.000401, 20, 0, 0],
], ids=["latitude-above", "longitude-below"])
def test_c2_rejects_cells_just_outside_snap_limit(cell):
    """C2: A cell just past either limit must not be rounded onto the grid."""
    cells = [[38.0, -123.0, 20, 0, 0], [38.08, -122.92, 20, 0, 0], cell]
    with pytest.raises(WcofsEddiesError) as caught:
        eddy_tiles(_layer({"time": _EARLY, "cells": cells}))
    assert type(caught.value) is WcofsEddiesError


@pytest.mark.parametrize("offset", [0, 0.0001], ids=["exact", "same-snapped-point"])
def test_c2_rejects_duplicate_grid_point_even_if_first_cell_was_missing(offset):
    """C2: Using grid values as an occupancy flag loses duplicates on masked cells."""
    cells = [[38.0, -123.0, 20, None, None], [38.0, -123.0 + offset, 20, 1, 2]]
    with pytest.raises(WcofsEddiesError) as caught:
        eddy_tiles(_layer({"time": _EARLY, "cells": cells}))
    assert type(caught.value) is WcofsEddiesError


def _vortex_cells() -> list[list]:
    cells = []
    for i in range(21):
        lat = 37.6 + i * 0.04
        y = (lat - 38) * 111_195
        for j in range(21):
            lon = -123.4 + j * 0.04
            x = (lon + 123) * 111_195 * math.cos(math.radians(38))
            rate = 1e-5 * math.exp(-(x*x + y*y) / (2 * 10_000**2))
            cells.append([round(lat, 6), round(lon, 6), 20, -rate * y, rate * x])
    return cells[::-1]


def test_c3_encodes_vortex_and_flat_flow_at_their_own_times():
    """C3: Catch reused frame grids, lost zero-eddy frames or mislabelled tiles."""
    flat = [[30 + i * 0.04, -120 + j * 0.04, 20, 0.5, -0.25]
            for i in range(3) for j in range(3)]
    result = eddy_tiles(_layer({"time": _LATE, "cells": flat},
                               {"time": _EARLY, "cells": _vortex_cells()}))
    assert result == [
        {"time": _EARLY, "eddies": 1, "tile": {"frame_time": "2026-01-01T00:00:00Z", "features": [{
            "outline": [
                [-123.06, 37.9], [-123.02, 37.9], [-122.98, 37.9], [-122.94, 37.9],
                [-122.94, 37.94], [-122.9, 37.94], [-122.9, 37.98], [-122.9, 38.02],
                [-122.9, 38.06], [-122.94, 38.06], [-122.94, 38.1], [-122.98, 38.1],
                [-123.02, 38.1], [-123.06, 38.1], [-123.06, 38.06], [-123.1, 38.06],
                [-123.1, 38.02], [-123.1, 37.98], [-123.1, 37.94], [-123.06, 37.94],
                [-123.06, 37.9],
            ],
            "sense": "ccw", "diameter_km": 20.42, "ow_min": -3.407e-10,
        }]}},
        {"time": _LATE, "eddies": 0, "tile": {"frame_time": "2026-01-01T03:00:00Z", "features": []}},
    ]


def test_c3_no_frames_returns_no_tiles():
    """C3: Catch a synthetic default tile in the absence of any frames."""
    result = eddy_tiles(_layer())
    assert result == []


def test_c3_duplicate_frame_time_is_an_error():
    """C3: Catch overwriting or emitting two tiles for one time."""
    cells = [[30 + i * 0.04, -120 + j * 0.04, 20, 0, 0] for i in range(3) for j in range(3)]
    frame = {"time": _EARLY, "cells": cells}
    with pytest.raises(WcofsEddiesError) as caught:
        eddy_tiles(_layer(frame, dict(frame)))
    assert type(caught.value) is WcofsEddiesError


@pytest.mark.parametrize("cells", [[], [[38, -123, 20, 0, 0]]], ids=["empty", "single-point"])
def test_c3_detector_error_propagates_for_undersized_grid(cells):
    """C3: Catch swallowing or relabelling a detector error as adapter validation."""
    with pytest.raises(EddyGridError) as caught:
        eddy_tiles(_layer({"time": _EARLY, "cells": cells}))
    assert type(caught.value) is EddyGridError


def test_c3_encoder_error_propagates(monkeypatch):
    """C3: Catch swallowing a real encoder refusal (diameter rounds to zero)."""
    def detect(lats, lons, u, v, frame_time):
        return [{"outline": [[-123, 38], [-122, 38], [-122, 39], [-123, 39], [-123, 38]],
                 "sense": "cw", "diameter_km": 0.001, "ow_min": -3e-10}]

    monkeypatch.setattr(wcofs_eddies, "eddies_for", detect)
    frame = {"time": _EARLY, "cells": [[38, -123, 20, 0, 0]]}
    with pytest.raises(EddyTileError) as caught:
        eddy_tiles(_layer(frame))
    assert type(caught.value) is EddyTileError

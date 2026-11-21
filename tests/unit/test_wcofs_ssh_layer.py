"""Offline layer and tile contracts for the WCOFS zeta adapter."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone, tzinfo
import hashlib
import json

import pytest

from skippercast.pipeline.habitat_dynamics import publish_tiles
from skippercast.pipeline.wcofs_ssh import WcofsSshError
from skippercast.pipeline.wcofs_ssh_layer import SSH_FIELDS, SSH_LAYER_ID, SshLayerError, ssh_layer

ISSUE = datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1)))
EARLY = 1767225600
LATE = EARLY + 10800
RESOLUTION = [0.04, 0.04]


def _frames():
    return [
        {"time": LATE, "latitudes": [35.0, 35.04], "longitudes": [-121.02, -120.98],
         "zeta": [[8, float("nan")], [-9999, 10]], "units": "meters", "fill_value": -9999},
        {"time": EARLY, "latitudes": [35.0, 35.04], "longitudes": [-121.02, -120.98],
         "zeta": [[1, 2], [3, 4]], "units": "m", "source_file": "synthetic.f000.nc"},
    ]


def test_c1_public_names():
    """C1: Catch renamed exports, reordered fields, or an incompatible error base."""
    assert SSH_LAYER_ID == "wcofs-ssh"
    assert SSH_FIELDS == ("latitude", "longitude", "ssh_cm")
    assert SshLayerError.__bases__ == (ValueError,)


def test_c1_converter_error_propagates():
    """C1: Catch wrapping a provider conversion error in a layer error."""
    frame = {**_frames()[1], "units": "cm"}
    with pytest.raises(WcofsSshError) as caught:
        ssh_layer([frame], ISSUE, RESOLUTION)
    assert type(caught.value) is WcofsSshError
    assert caught.value.args == ("WCOFS zeta units must be metres",)
    assert caught.value.__cause__ is None


def test_c2_and_c3_exact_sorted_layer():
    """C2: Catch reordered cells, lost masks or whole-grid rather than per-frame means.

    C3: Catch incomplete layer metadata, a local issue stamp, or wrong totals.
    """
    frames = _frames()
    before = deepcopy(frames)
    resolution = (0.04, 0.25)
    result = ssh_layer(frames, ISSUE, resolution)
    assert result == {
        "id": "wcofs-ssh",
        "kind": "forecast",
        "issued_at": "2026-01-01T00:00:00Z",
        "resolution_degrees": (0.04, 0.25),
        "horizontal_datum": "NAD83",
        "vertical_layer": "surface 0 m",
        "surface_only": True,
        "fields": ["latitude", "longitude", "ssh_cm"],
        "frames": [
            {"time": EARLY, "cells": [[35.0, -121.02, -150.0], [35.0, -120.98, -50.0],
                                     [35.04, -121.02, 50.0], [35.04, -120.98, 150.0]],
             "valid_cells": 4, "total_cells": 4, "source_file": "synthetic.f000.nc"},
            {"time": LATE, "cells": [[35.0, -121.02, -100.0], [35.04, -120.98, 100.0]],
             "valid_cells": 2, "total_cells": 4, "source_file": None},
        ],
        "valid_cells": 6,
        "total_cells": 8,
        "valid_from": EARLY,
        "valid_through": LATE,
        "source_url": "https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html",
        "license": "Public NOAA model data; retain attribution",
        "native_stride": 1,
        "limitations": (
            "Approximately 4 km model with three-hour output and at most 72-hour forecast. "
            "Sea-surface height relative to the regional mean of each frame, in centimetres; "
            "model output, not observed altimetry. No SkipperCast spatial or temporal gap filling."
        ),
    }
    # C4: Catch sorting or masking the caller's frame data in place.
    assert frames == before


@pytest.mark.parametrize("count", [0, 170], ids=["empty", "over-limit"])
def test_c4_rejects_bad_frame_count(count):
    """C4: Catch accepting an empty or oversized frame list."""
    frames = [dict(_frames()[1], time=EARLY + i) for i in range(count)]
    with pytest.raises(SshLayerError) as caught:
        ssh_layer(frames, ISSUE, RESOLUTION)
    assert type(caught.value) is SshLayerError


def test_c4_rejects_duplicate_time():
    """C4: Catch silently accepting or deduplicating frame timestamps."""
    frames = _frames()
    frames[0]["time"] = EARLY
    with pytest.raises(SshLayerError) as caught:
        ssh_layer(frames, ISSUE, RESOLUTION)
    assert type(caught.value) is SshLayerError


@pytest.mark.parametrize("bad_time", [float(EARLY), str(EARLY), True, False])
def test_c4_rejects_non_integer_times(bad_time):
    """C4: Catch coercion of strings, integral floats, or bools into epoch seconds."""
    frame = {**_frames()[1], "time": bad_time}
    with pytest.raises(SshLayerError) as caught:
        ssh_layer([frame], ISSUE, RESOLUTION)
    assert type(caught.value) is SshLayerError


class _NoOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize("zone", [None, _NoOffset()], ids=["no-zone", "no-offset"])
def test_c4_rejects_naive_issue_time(zone):
    """C4: Catch interpreting issue time in the host timezone or checking tzinfo alone."""
    with pytest.raises(SshLayerError) as caught:
        ssh_layer(_frames(), ISSUE.replace(tzinfo=zone), RESOLUTION)
    assert type(caught.value) is SshLayerError


@pytest.mark.parametrize("resolution", [
    None, 0.04, [], [0.04], [0.04, 0.04, 0.04], "04", {0: 0.04, 1: 0.04},
    [0.04, "0.04"], [0.04, True], [0.04, False], [0.04, 0.04 + 0j],
    [0.04, 0], [0.04, -0.04], [0.251, 0.04], [0.04, 10**400],
    [0.04, float("nan")], [0.04, float("inf")], [0.04, -float("inf")],
])
def test_c4_rejects_invalid_resolution(resolution):
    """C4: Catch truncation, coercion, non-finite sizes, and bad grid bounds."""
    with pytest.raises(SshLayerError) as caught:
        ssh_layer(_frames(), ISSUE, resolution)
    assert type(caught.value) is SshLayerError


def test_c5_publish_tiles_round_trip(tmp_path):
    """C5: Catch misplaced rows, lost times, or metadata that doesn't bind the tile bytes."""
    layer = ssh_layer(_frames(), ISSUE, RESOLUTION)
    result = publish_tiles(layer, tmp_path, "offline-fixture")
    expected_tiles = [
        (-243, [-121.5, 35.0, -121.0, 35.5], [
            {"time": EARLY, "cells": [[35.0, -121.02, -150.0], [35.04, -121.02, 50.0]], "valid_cells": 2},
            {"time": LATE, "cells": [[35.0, -121.02, -100.0]], "valid_cells": 1},
        ]),
        (-242, [-121.0, 35.0, -120.5, 35.5], [
            {"time": EARLY, "cells": [[35.0, -120.98, -50.0], [35.04, -120.98, 150.0]], "valid_cells": 2},
            {"time": LATE, "cells": [[35.04, -120.98, 100.0]], "valid_cells": 1},
        ]),
    ]
    assert len(result["tiles"]) == len(expected_tiles)
    descriptors = []
    for descriptor, (xi, bounds, frames) in zip(result["tiles"], expected_tiles, strict=True):
        data = (tmp_path / descriptor["path"]).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        descriptors.append({"path": f"habitat-tiles/wcofs-ssh-{xi}-70-{sha[:16]}.json",
                            "bounds": bounds, "sha256": sha, "bytes": len(data)})
        assert json.loads(data) == {
            "schema_version": 1, "region_id": "offline-fixture", "layer_id": "wcofs-ssh",
            "bounds": bounds, "resolution_degrees": [0.04, 0.04],
            "fields": ["latitude", "longitude", "ssh_cm"], "frames": frames,
        }
    assert result == {
        **layer,
        "frames": [
            {"time": EARLY, "valid_cells": 4, "total_cells": 4, "source_file": "synthetic.f000.nc"},
            {"time": LATE, "valid_cells": 2, "total_cells": 4, "source_file": None},
        ],
        "tiles": descriptors,
    }

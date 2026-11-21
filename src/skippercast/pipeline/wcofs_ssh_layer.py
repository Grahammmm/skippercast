"""Assemble WCOFS sea-surface height frames for the habitat tile writer."""

from datetime import datetime

from .collect import stamp
from .habitat_dynamics import WCOFS_DOC
from .wcofs_ssh import ssh_rows

SSH_LAYER_ID = "wcofs-ssh"
SSH_FIELDS = ("latitude", "longitude", "ssh_cm")


class SshLayerError(ValueError):
    """The frames or metadata cannot form an SSH layer."""


def ssh_layer(frames, issued_at: datetime, resolution) -> dict:
    """Build a forecast layer from preloaded zeta frames without I/O."""
    if not 1 <= len(frames) <= 169:
        raise SshLayerError("SSH layer requires 1 to 169 frames")
    if issued_at.utcoffset() is None:
        raise SshLayerError("SSH layer issue time must be timezone-aware")
    if not isinstance(resolution, (list, tuple)) or len(resolution) != 2 or not all(
        isinstance(step, (int, float)) and not isinstance(step, bool) and 0 < step <= 0.25
        for step in resolution
    ):
        raise SshLayerError("SSH layer requires two resolution values in (0, 0.25]")

    times = set()
    output_frames = []
    for frame in frames:
        time = frame["time"]
        if not isinstance(time, int) or isinstance(time, bool):
            raise SshLayerError("SSH frame time must be an integer epoch second")
        if time in times:
            raise SshLayerError("Duplicate SSH frame time")
        times.add(time)

        latitudes, longitudes = frame["latitudes"], frame["longitudes"]
        rows = ssh_rows(latitudes, longitudes, frame["zeta"], frame["units"], frame.get("fill_value"))
        cells = [[row[field] for field in SSH_FIELDS] for row in rows]
        output_frames.append({
            "time": time,
            "cells": cells,
            "valid_cells": len(cells),
            "total_cells": len(latitudes) * len(longitudes),
            "source_file": frame.get("source_file"),
        })
    output_frames.sort(key=lambda frame: frame["time"])

    return {
        "id": SSH_LAYER_ID,
        "kind": "forecast",
        "issued_at": stamp(issued_at),
        "resolution_degrees": resolution,
        "horizontal_datum": "NAD83",
        "vertical_layer": "surface 0 m",
        "surface_only": True,
        "fields": list(SSH_FIELDS),
        "frames": output_frames,
        "valid_cells": sum(frame["valid_cells"] for frame in output_frames),
        "total_cells": sum(frame["total_cells"] for frame in output_frames),
        "valid_from": output_frames[0]["time"],
        "valid_through": output_frames[-1]["time"],
        "source_url": WCOFS_DOC,
        "license": "Public NOAA model data; retain attribution",
        "native_stride": 1,
        "limitations": (
            "Approximately 4 km model with three-hour output and at most 72-hour forecast. "
            "Sea-surface height relative to the regional mean of each frame, in centimetres; "
            "model output, not observed altimetry. No SkipperCast spatial or temporal gap filling."
        ),
    }

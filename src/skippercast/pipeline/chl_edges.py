"""Detect chlorophyll colour edges on one observed grid, without filling gaps."""

from collections import deque
from datetime import datetime, timezone
import math


MIN_LOG10_CHANGE_PER_CELL = 0.3
MIN_EDGE_CELLS = 5
# Two coordinates rounded to five decimals (the sample and the origin) can
# differ from the ideal spacing by up to 1e-5 degrees, as for SST fronts.
COORDINATE_TOLERANCE_DEGREES = 1.01e-5
KM_PER_DEGREE = 111.195
AXES = ((0, 1), (1, 0))  # longitude wins a tie in dominant direction
STEPS = ((0, -1), (-1, 0), (1, 0), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))


class ChlEdgeError(ValueError):
    """The supplied observation cannot be used to detect edges."""


def _number(value, name):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
            if math.isfinite(number):
                return number
        except OverflowError:
            pass
    raise ChlEdgeError(f"{name} must be a finite number")


def _grid(rows, resolution):
    samples = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ChlEdgeError("expected a row of latitude, longitude and chlorophyll")
        lat = _number(row[0], "latitude")
        lon = _number(row[1], "longitude")
        chl = _number(row[2], "chlorophyll")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ChlEdgeError("latitude or longitude is out of range")
        if chl <= 0:
            raise ChlEdgeError("chlorophyll must be positive")
        samples.append((lat, lon, chl))
    if not samples:
        return {}

    origin_lat = min(row[0] for row in samples)
    origin_lon = min(row[1] for row in samples)
    tolerance = min(COORDINATE_TOLERANCE_DEGREES, resolution / 10)
    grid = {}
    for lat, lon, chl in samples:
        y, x = (lat - origin_lat) / resolution, (lon - origin_lon) / resolution
        if not (math.isfinite(y) and math.isfinite(x)):
            raise ChlEdgeError("grid spacing is too small to address the cells")
        cell = (round(y), round(x))
        if max(abs(y - cell[0]), abs(x - cell[1])) * resolution > tolerance:
            raise ChlEdgeError(f"cell at ({lat}, {lon}) is off the tile lattice")
        sample = (lat, lon, chl)
        if grid.setdefault(cell, sample) != sample:
            raise ChlEdgeError(f"conflicting overlapping measurements at grid address {cell}")
    return grid


def _ridge(grid):
    logs = {cell: math.log10(sample[2]) for cell, sample in grid.items()}
    gradients = {}
    for i, j in grid:
        changes = []
        for di, dj in AXES:
            before, after = logs.get((i - di, j - dj)), logs.get((i + di, j + dj))
            changes.append(abs(after - before) / 2 if before is not None and after is not None else 0.0)
        gradients[i, j] = changes

    kept = {}
    for (i, j), changes in gradients.items():
        axis = 0 if changes[0] >= changes[1] else 1
        change = changes[axis]
        # Include the threshold itself, allowing for log10 round-off.
        if change < MIN_LOG10_CHANGE_PER_CELL and not math.isclose(change, MIN_LOG10_CHANGE_PER_CELL,
                                                                  rel_tol=0, abs_tol=1e-14):
            continue
        di, dj = AXES[axis]
        before = gradients.get((i - di, j - dj), (0, 0))[axis]
        after = gradients.get((i + di, j + dj), (0, 0))[axis]
        if before < change >= after:  # keep the first cell of a two-cell step ridge
            kept[i, j] = (change, axis)
    return kept


def _lines(kept, grid):
    links = {}
    for i, j in kept:
        links[i, j] = [(i + di, j + dj) for di, dj in STEPS
                       if (i + di, j + dj) in kept
                       # A diagonal must not cut across a missing corner.
                       and (not (di and dj) or ((i + di, j) in grid and (i, j + dj) in grid))]
    left = set(kept)
    for start in sorted(kept, key=lambda cell: (len(links[cell]), cell)):
        if start not in left:
            continue
        line = deque([start])
        left.remove(start)
        for first in (False, True):
            end = start
            while (neighbour := next((cell for cell in links[end] if cell in left), None)) is not None:
                left.remove(neighbour)
                if first:
                    line.appendleft(neighbour)
                else:
                    line.append(neighbour)
                end = neighbour
        if len(line) >= MIN_EDGE_CELLS:
            yield line


def edges_for(rows, resolution, when):
    """Return SST-front-shaped LineString features from one pooled observation.

    Rows are (latitude, longitude, chlorophyll_mg_m3); omit cloud/land cells.
    Resolution is the common lat/lon step in degrees and `when` is an aware
    observation datetime. For each axis the score is the absolute difference
    in log10(chlorophyll) between both immediate neighbours, divided by two
    cells. The dominant supported score must be at least 0.3 log10 per cell.
    The mean of these scores is reported as `strength_log10_per_cell`.

    `band_half_width_km` is the mean of half a native cell across the ridge,
    using latitude-scaled longitude spacing where appropriate. It estimates
    grid-position uncertainty, not measurement error or a confidence interval.
    """
    resolution = _number(resolution, "resolution")
    if not 0 < resolution <= 180:
        raise ChlEdgeError("resolution must be a positive grid step in degrees")
    if not isinstance(when, datetime) or when.utcoffset() is None:
        raise ChlEdgeError("observation time must have a timezone")
    observed_at = when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    grid = _grid(rows, resolution)
    kept = _ridge(grid)
    out = []
    for line in _lines(kept, grid):
        coords = [[grid[cell][1], grid[cell][0]] for cell in line]
        width_factor = sum(math.cos(math.radians(grid[cell][0])) if kept[cell][1] == 0 else 1.0 for cell in line)
        out.append({"observed_at": observed_at, "cells": len(line),
                    "strength_log10_per_cell": sum(kept[cell][0] for cell in line) / len(line),
                    "band_half_width_km": resolution * KM_PER_DEGREE / 2 * (width_factor / len(line)),
                    "geometry": {"type": "LineString", "coordinates": coords}})
    out.sort(key=lambda feature: (-feature["cells"], feature["geometry"]["coordinates"]))
    for number, feature in enumerate(out, 1):
        feature["id"] = f"edge-{number}"
    return out

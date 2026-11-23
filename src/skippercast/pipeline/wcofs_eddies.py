"""Detect and encode surface-current eddies from offline WCOFS frames."""

from datetime import datetime, timezone
import math
from numbers import Real

from skippercast.pipeline.eddies import eddies_for
from skippercast.pipeline.eddies_tile import eddies_tile


class WcofsEddiesError(ValueError):
    """The surface layer metadata, grid registration, or frame times are invalid."""


def _positive_step(value: object) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        step = float(value)
        return math.isfinite(step) and step > 0
    except OverflowError:
        return False


def _axis(cells: list[list], column: int, step: float) -> list[float]:
    if not cells:
        return []  # Let the detector handle insufficient axes, like any undersized grid.
    coordinates = [cell[column] for cell in cells]
    start = min(coordinates)
    return [start + index * step for index in range(round((max(coordinates) - start) / step) + 1)]


def _snap(coordinate: float, axis: list[float], step: float) -> int:
    index = round((coordinate - axis[0]) / step)
    point, tolerance = axis[index], 0.01 * step
    # Compare against inclusive bounds in degrees to avoid cancellation at the edge.
    if not point - tolerance <= coordinate <= point + tolerance:
        raise WcofsEddiesError("cell is more than 1% of a step off the WCOFS grid")
    return index


def eddy_tiles(layer: dict) -> list[dict]:
    """Return one eddy tile per surface frame, ordered by UTC epoch time."""
    fields = layer.get("fields")
    if (not isinstance(fields, (list, tuple)) or tuple(fields[:2]) != ("latitude", "longitude")
            or "u_mps" not in fields or "v_mps" not in fields):
        raise WcofsEddiesError("fields must start with latitude, longitude and contain u_mps and v_mps")
    u_column, v_column = fields.index("u_mps"), fields.index("v_mps")
    resolution = layer.get("resolution_degrees")
    if (not isinstance(resolution, (list, tuple)) or len(resolution) != 2
            or not all(_positive_step(step) for step in resolution)):
        raise WcofsEddiesError("resolution_degrees must contain two finite positive steps [dy, dx]")
    dy, dx = resolution

    frames = sorted(layer["frames"], key=lambda frame: frame["time"])
    if len({frame["time"] for frame in frames}) != len(frames):
        raise WcofsEddiesError("duplicate WCOFS frame time")

    result = []
    for frame in frames:
        time = frame["time"]
        frame_time = datetime.fromtimestamp(time, timezone.utc)
        cells = frame["cells"]
        lats, lons = _axis(cells, 0, dy), _axis(cells, 1, dx)
        u: list[list[float | None]] = [[None] * len(lons) for _ in lats]
        v: list[list[float | None]] = [[None] * len(lons) for _ in lats]
        occupied: set[tuple[int, int]] = set()
        for cell in cells:
            i, j = _snap(cell[0], lats, dy), _snap(cell[1], lons, dx)
            if (i, j) in occupied:
                raise WcofsEddiesError("duplicate cell on the WCOFS grid")
            occupied.add((i, j))
            east, north = cell[u_column], cell[v_column]
            if east is not None and north is not None:
                u[i][j], v[i][j] = east, north
        features = eddies_for(lats, lons, u, v, frame_time)
        tile = eddies_tile(frame_time, features)
        result.append({"time": time, "tile": tile, "eddies": len(tile["features"])})
    return result

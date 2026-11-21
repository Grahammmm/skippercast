"""Offline Okubo–Weiss detection on a regular surface-current grid."""

from collections.abc import Sequence
import math
from numbers import Real
from statistics import pstdev
from typing import Literal, TypedDict

_METRES_PER_DEGREE = math.pi * 6_371_008.8 / 180
_THRESHOLD_SIGMAS = 0.2
_MIN_CORE_SPAN = 4
_NEIGHBOURS = ((-1, 0), (0, 1), (1, 0), (0, -1))
_Cell = tuple[int, int]


class EddyGridError(ValueError):
    """The supplied axes or velocity grids do not match the grid contract."""


class EddyFeature(TypedDict):
    outline: list[list[float]]
    sense: Literal["cw", "ccw"]
    diameter_km: float
    ow_min: float


def _sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _number(value, label):
    if isinstance(value, Real) and not isinstance(value, bool):
        try:
            return float(value)
        except OverflowError:
            pass
    raise EddyGridError(f"{label} must contain real numbers")


def _axis(values, name, limit):
    if not _sequence(values) or len(values) < 3:
        raise EddyGridError(f"{name} needs at least three coordinates")
    axis = [_number(value, name) for value in values]
    if not all(-limit <= value <= limit for value in axis):
        raise EddyGridError(f"{name} coordinates must be finite and within ±{limit} degrees")
    step = (axis[-1] - axis[0]) / (len(axis) - 1)
    # Allow quantization of degree axes stored as float32, not reversed or duplicate steps.
    tolerance = min(2e-5, abs(step) * 0.01)
    if step == 0 or any(abs(b - a - step) > tolerance for a, b in zip(axis, axis[1:])):
        raise EddyGridError(f"{name} must be strictly monotonic and regularly spaced")
    return axis


def _velocity_grid(grid, name, ny, nx):
    if not _sequence(grid) or len(grid) != ny:
        raise EddyGridError(f"{name} must have {ny} latitude rows")
    values = []
    for i, row in enumerate(grid):
        if not _sequence(row) or len(row) != nx:
            raise EddyGridError(f"{name} row {i} must have {nx} longitude columns")
        values.append([math.nan if value is None else _number(value, name) for value in row])
    return values


def _ow_field(u, v, dy, dx, row_scale):
    """Return (W, omega) only where the centre and all four neighbours are wet."""
    wet = [[math.isfinite(a) and math.isfinite(b) for a, b in zip(ur, vr)] for ur, vr in zip(u, v)]
    field = {}
    for i in range(1, len(u) - 1):
        for j in range(1, len(u[i]) - 1):
            if not wet[i][j] or not all(wet[i + di][j + dj] for di, dj in _NEIGHBOURS):
                continue
            east_span = dx[j] * row_scale[i]
            ux = (u[i][j + 1] - u[i][j - 1]) / east_span
            vx = (v[i][j + 1] - v[i][j - 1]) / east_span
            uy = (u[i + 1][j] - u[i - 1][j]) / dy[i]
            vy = (v[i + 1][j] - v[i - 1][j]) / dy[i]
            sn, ss, omega = ux - vy, vx + uy, vx - uy
            ow = sn * sn + ss * ss - omega * omega
            if math.isfinite(ow):
                field[i, j] = ow, omega
    return field


def _components(candidates):
    remaining = set(candidates)
    for start in candidates:  # row-major seeds give deterministic feature order
        if start not in remaining:
            continue
        remaining.remove(start)
        core = [start]
        for i, j in core:
            for di, dj in _NEIGHBOURS:
                cell = i + di, j + dj
                if cell in remaining:
                    remaining.remove(cell)
                    core.append(cell)
        yield core


def _boundary(core):
    """Trace one unambiguous closed ring along exposed cell edges, or refuse it."""
    cells = set(core)
    edges = {}
    for i, j in core:
        corners = ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j))
        for k, (di, dj) in enumerate(_NEIGHBOURS):
            if (i + di, j + dj) not in cells:
                start = corners[k]
                if start in edges:  # A corner pinch cannot be expressed as a simple ring.
                    return None
                edges[start] = corners[(k + 1) % 4]
    start = min(edges)
    ring = [start]
    while True:
        ring.append(edges[ring[-1]])
        if ring[-1] == start:
            # Another ring would be a hole; the feature format only has one outline.
            return ring if len(ring) == len(edges) + 1 else None


def _midpoints(axis):
    return [(a + b) / 2 for a, b in zip(axis, axis[1:])]


def eddies_for(lats, lons, u, v, frame_time) -> list[EddyFeature]:
    """Detect eddies in one frame; the caller uses ``frame_time`` to label the result.

    Axes are 1-D sequences of degrees (either direction, no longitude wrap).
    The m/s velocity grids are latitude-major, with None or non-finite values
    marking missing cells. No derivative is taken across a gap. Invalid grid
    shapes, axes or non-numeric velocity entries raise ``EddyGridError``.

    Use local east/north distances (longitude scaled by cos(latitude)) and keep
    four-neighbour cores strictly below -0.2 times the population std of valid
    W values. Require a span of four cells in both axes. Drop cores that reach
    the outermost computable row/column: the centred stencil cannot confirm
    closure at the subset edge. Drop cores without a single simple outline.

    The outline is a closed [lon, lat] ring on cell edges. Diameter is that of a
    circle with the same summed cell area, and sense uses omega at minimum W
    (positive is counter-clockwise). No time filtering or feed I/O happens here.
    """
    lat, lon = _axis(lats, "lats", 90), _axis(lons, "lons", 180)
    ny, nx = len(lat), len(lon)
    u, v = _velocity_grid(u, "u", ny, nx), _velocity_grid(v, "v", ny, nx)
    lat_edges, lon_edges = _midpoints(lat), _midpoints(lon)
    dy = [0.0] + [(b - a) * _METRES_PER_DEGREE for a, b in zip(lat, lat[2:])]
    dx = [0.0] + [(b - a) * _METRES_PER_DEGREE for a, b in zip(lon, lon[2:])]
    row_scale = [math.cos(math.radians(value)) for value in lat]
    field = _ow_field(u, v, dy, dx, row_scale)
    if not field:
        return []
    threshold = -_THRESHOLD_SIGMAS * pstdev(ow for ow, _ in field.values())
    candidates = [cell for cell, (ow, _) in field.items() if ow < threshold]

    features = []
    for core in _components(candidates):
        rows, cols = zip(*core)
        top, bottom, left, right = min(rows), max(rows), min(cols), max(cols)
        if top == 1 or left == 1 or bottom == ny - 2 or right == nx - 2:
            continue
        if min(bottom - top + 1, right - left + 1) < _MIN_CORE_SPAN:
            continue
        ring = _boundary(core)
        if ring is None:
            continue
        if (lat[-1] > lat[0]) != (lon[-1] > lon[0]):
            ring.reverse()
        # The width and height of each cell are half its centred stencil spans.
        area = math.fsum(abs(dy[i] * dx[j]) * row_scale[i] / 4 for i, j in core)
        ow_min, omega = min(field[cell] for cell in core)
        features.append({
            "outline": [[lon_edges[j - 1], lat_edges[i - 1]] for i, j in ring],
            "sense": "ccw" if omega > 0 else "cw",
            "diameter_km": 2 * math.sqrt(area / math.pi) / 1000,
            "ow_min": ow_min,
        })
    return features

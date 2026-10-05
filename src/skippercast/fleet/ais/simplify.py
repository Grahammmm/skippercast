"""Track simplification and Google encoded polylines (design.md sections 5 and 11).

Each segment's positions are simplified with Douglas-Peucker on a local
equirectangular projection, then stored in ``fleet_segments.geometry`` as a
Google encoded polyline at precision 5. ``server/fleet/map.ts``
``decodePolyline`` reads it back, so the encoder here mirrors that decoder (and
the reference algorithm): values are rounded half up like JavaScript's
``Math.round``, deltas are taken between the rounded integers so error never
accumulates, and points are encoded latitude first.

Standard library only; pure functions.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

__all__ = ["METRES_PER_DEG", "PRECISION", "decode_polyline", "encode_polyline", "simplify", "simplify_encode"]

PRECISION = 5
METRES_PER_DEG = 111_320.0  # metres per degree of latitude (and of longitude at the equator)

Point = tuple[float, float]  # (lat, lon)


def _project(points: Sequence[Point]) -> list[tuple[float, float]]:
    """Metres east and north of the first point, on an equirectangular projection at the mean latitude."""
    lat0 = sum(p[0] for p in points) / len(points)
    kx = METRES_PER_DEG * math.cos(math.radians(lat0))
    base_lat, base_lon = points[0]
    return [((lon - base_lon) * kx, (lat - base_lat) * METRES_PER_DEG) for lat, lon in points]


def _offset(p, a, b) -> float:
    """Distance in metres from p to the segment a-b (projected)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    if length == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def simplify(points: Sequence[Point], tolerance_m: float) -> list[Point]:
    """Douglas-Peucker: the subset of ``points`` (first and last always kept) within ``tolerance_m`` of the input.

    Every dropped point lies within ``tolerance_m`` metres of the simplified line
    (on the local projection). Iterative, so long tracks cannot hit the recursion limit.
    """
    pts = list(points)
    if tolerance_m < 0 or not math.isfinite(tolerance_m):
        raise ValueError("tolerance_m must be a finite number >= 0")
    if len(pts) <= 2:
        return pts
    xy = _project(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        worst, index = -1.0, -1
        for k in range(first + 1, last):
            d = _offset(xy[k], xy[first], xy[last])
            if d > worst:
                worst, index = d, k
        if worst > tolerance_m:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, kept in zip(pts, keep) if kept]


def _round_half_up(value: float) -> int:
    """JavaScript ``Math.round``: halves round towards +infinity."""
    return math.floor(value + 0.5)


def _encode_value(value: int) -> str:
    n = ~(value << 1) if value < 0 else value << 1
    out = []
    while n >= 0x20:
        out.append(chr((0x20 | (n & 0x1F)) + 63))
        n >>= 5
    out.append(chr(n + 63))
    return "".join(out)


def encode_polyline(points: Iterable[Point], precision: int = PRECISION) -> str:
    """Google encoded polyline of (lat, lon) points."""
    factor = 10 ** precision
    out, prev_lat, prev_lon = [], 0, 0
    for lat, lon in points:
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError("polyline points must be finite")
        ilat, ilon = _round_half_up(lat * factor), _round_half_up(lon * factor)
        out.append(_encode_value(ilat - prev_lat))
        out.append(_encode_value(ilon - prev_lon))
        prev_lat, prev_lon = ilat, ilon
    return "".join(out)


def decode_polyline(encoded: str, precision: int = PRECISION) -> list[Point]:
    """(lat, lon) points of a Google encoded polyline; ``[]`` when malformed (as ``map.ts`` does)."""
    factor = 10 ** precision
    index, lat, lon, out = 0, 0, 0, []

    def next_value():
        nonlocal index
        result = shift = 0
        while True:
            if index >= len(encoded):
                return None
            byte = ord(encoded[index]) - 63
            index += 1
            if byte < 0 or byte > 63 or shift > 30:
                return None
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        return ~(result >> 1) if result & 1 else result >> 1

    while index < len(encoded):
        d_lat, d_lon = next_value(), next_value()
        if d_lat is None or d_lon is None:
            return []
        lat += d_lat
        lon += d_lon
        out.append((round(lat / factor, precision), round(lon / factor, precision)))
    return out


def simplify_encode(points: Sequence[Point], tolerance_m: float, precision: int = PRECISION) -> str | None:
    """Simplify then encode; None when there are no points (a ``gap`` segment has no geometry)."""
    if not points:
        return None
    return encode_polyline(simplify(points, tolerance_m), precision)

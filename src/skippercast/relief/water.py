"""Offline regional ocean masks using the reviewed north-B shoreline opening."""

from math import ceil, floor, isfinite
from typing import Iterable, cast

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box, mapping

_QUAD_SEGS = 8
_FRAME_GRID = 100_000
_FRAME_SEGMENT_DEG = 0.005
_OUTPUT_GRID = 0.000001


def _project(geometry, transformer):
    return shapely.transform(geometry, transformer.transform, interleaved=False)


def _wgs84(geometry):
    xy = shapely.get_coordinates(geometry)
    return bool(np.isfinite(xy).all() and (np.abs(xy) <= [180, 90]).all())


def _frame_bounds(bounds):
    w, s, e, n = bounds
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("expected ordered WGS84 frame bounds")

    def snap(value, inward):
        scaled = value * _FRAME_GRID
        # Preserve points already on the grid despite binary floating point.
        nearest = round(scaled)
        cell = nearest if nearest / _FRAME_GRID == value else inward(scaled)
        return cell / _FRAME_GRID

    w, s, e, n = snap(w, ceil), snap(s, ceil), snap(e, floor), snap(n, floor)
    if not (w < e and s < n):
        raise ValueError("frame vanishes on the five-decimal grid")
    return w, s, e, n


def _project_frame(bounds, forward):
    w, s, e, n = bounds
    mid = (s + n) / 2
    # Include the seed as a vertex. Projecting it separately onto a chord of
    # a curved meridian can leave it slightly outside the projected frame.
    ring = LineString([(e, s), (e, n), (w, n), (w, mid), (w, s), (e, s)])
    east = LineString([(e, s), (e, n)])
    return (
        Polygon(_project(shapely.segmentize(ring, _FRAME_SEGMENT_DEG), forward)),
        _project(shapely.segmentize(east, _FRAME_SEGMENT_DEG), forward),
        _project(Point(w, mid), forward),
    )


def _west_part(geometry, seed):
    parts = [p for p in shapely.get_parts(geometry) if isinstance(p, Polygon) and not p.is_empty]
    west = [i for i, p in enumerate(parts) if p.distance(seed) < 1e-6]
    if len(west) != 1:
        raise ValueError("expected exactly one component at the west-frame seed")
    return parts.pop(west[0]), parts


def _line_parts(geometry):
    if isinstance(geometry, LineString) and geometry.length:
        yield geometry
    elif isinstance(geometry, (GeometryCollection, MultiLineString)):
        for part in geometry.geoms:
            yield from _line_parts(part)


def _buffer(geometry, radius):
    return geometry.buffer(radius, quad_segs=_QUAD_SEGS)


def _cut_east(ocean, frame, east, seed, lines, close_m, connect_m):
    if not ocean.intersects(east):
        return ocean, [], []

    # Re-open the clearance core at the larger radius, reconstruct it only
    # back to close_m, and remove only residual pieces that touch the east.
    # In particular this must not remove bays merely because they are narrow.
    west_core, _ = _west_part(frame.difference(_buffer(lines, connect_m)), seed)
    core = ocean.intersection(_buffer(west_core, connect_m - close_m))
    cut_pieces = [p for p in shapely.get_parts(ocean.difference(core)) if p.intersects(east)]
    cut_union = shapely.union_all(cut_pieces)
    kept, detached = _west_part(ocean.difference(cut_union), seed)
    if kept.intersects(east):
        raise ValueError("ocean still reaches the east frame after connectivity cuts")
    arcs = shapely.line_merge(kept.boundary.intersection(cut_union.buffer(0.5)))
    return kept, cut_pieces + detached, list(_line_parts(arcs))


def _position(point, inverse, decimals):
    return [round(v, decimals) for v in inverse.transform(point.x, point.y)]


def _displacement(shore_m, lines_m, cut_arcs_m, close_m, inverse):
    """Score the non-frame boundary in metres; listed cuts exempt flags, not the max."""
    bound = 2 * close_m
    cuts = shapely.union_all(cut_arcs_m)
    maximum = 0.0
    beyond = []
    for part in _line_parts(shore_m):
        steps = np.append(np.arange(0, part.length, 2.0), part.length)
        samples = shapely.line_interpolate_point(part, steps.tolist())
        distances = shapely.distance(samples, lines_m)
        maximum = max(maximum, float(distances.max()))
        outliers = samples[distances > bound + 0.5]
        if not cuts.is_empty:
            outliers = outliers[shapely.distance(outliers, cuts) > close_m + 1]
        beyond.extend(_position(p, inverse, 5) for p in outliers)
    return {
        "max_displacement_m": round(maximum, 2),
        "displacement_bound_m": bound,
        "unlisted_beyond_bound": sorted(beyond),
    }


def _output_polygon(ocean, frame_ll, inverse) -> Polygon | MultiPolygon:
    water = _project(ocean, inverse)
    if not water.is_valid:
        # Repair only projection artefacts of the derived polygon.
        water = shapely.union_all([
            p for p in shapely.get_parts(shapely.make_valid(water)) if isinstance(p, (Polygon, MultiPolygon))
        ])
    water = shapely.set_precision(water, _OUTPUT_GRID).intersection(frame_ll)
    polygons = [p for p in shapely.get_parts(water) if isinstance(p, Polygon) and p.area > 0]
    if not polygons:
        raise ValueError("empty ocean on the output grid")
    return cast(Polygon | MultiPolygon, shapely.orient_polygons(shapely.union_all(polygons).normalize()))


def ocean_polygon(
    lines: Iterable[tuple[LineString, float]],
    frame: tuple[float, float, float, float],
    *,
    close_m: float,
    connect_m: float,
) -> tuple[Polygon | MultiPolygon, dict]:
    """Return a WGS84 ocean polygon and its review report, without I/O.

    ``lines`` pairs each WGS84 LineString with its stated horizontal accuracy
    in metres. Supply the maximum of these accuracies as ``close_m`` and a
    connectivity radius ``connect_m`` at least that large.
    ``frame`` is (west, south, east, north) in WGS84; the method
    assumes the ocean contains its west midpoint and the east edge is inland.
    An ambiguous seed or an unresolved east leak is refused.

    Dropped components describe the clearance-stage polygons (WGS84 bounds
    and EPSG:3310 areas). Cut arcs describe the clearance-stage cut seams as
    WGS84 positions and metric lengths, before the final close_m dilation.
    Unlisted displacements are reported, not refused.
    """
    if not (isfinite(close_m) and isfinite(connect_m) and 0 < close_m <= connect_m):
        raise ValueError("expected finite radii with 0 < close_m <= connect_m")
    bounds = _frame_bounds(frame)
    raw, accuracies = [], []
    for line, accuracy in lines:
        if (not isinstance(line, LineString) or line.is_empty or shapely.get_coordinate_dimension(line) != 2
                or not _wgs84(line) or not line.length or not isfinite(accuracy) or accuracy <= 0):
            raise ValueError("expected nonempty 2D WGS84 shoreline and positive horizontal accuracy")
        raw.append(line)
        accuracies.append(accuracy)
    if not raw or max(accuracies) != close_m:
        raise ValueError("close_m must equal the maximum stated shoreline accuracy")

    forward = Transformer.from_crs(4326, 3310, always_xy=True)
    inverse = Transformer.from_crs(3310, 4326, always_xy=True)
    frame_ll = box(*bounds)
    frame_m, east, seed = _project_frame(bounds, forward)
    lines_m = _project(MultiLineString(raw), forward)
    # Erode against the shoreline, not against the frame; dilate only the
    # retained ocean component and clip the result back to the same frame.
    ocean, dropped = _west_part(frame_m.difference(_buffer(lines_m, close_m)), seed)
    ocean, cut_dropped, arcs = _cut_east(ocean, frame_m, east, seed, lines_m, close_m, connect_m)
    water = _output_polygon(_buffer(ocean, close_m).intersection(frame_m), frame_ll, inverse)

    cut_arcs = []
    for arc in arcs:
        arc = arc.normalize()
        cut_arcs.append({
            "from_lon_lat": _position(arc.interpolate(0), inverse, 6),
            "to_lon_lat": _position(arc.interpolate(1, normalized=True), inverse, 6),
            "mid_lon_lat": _position(arc.interpolate(0.5, normalized=True), inverse, 6),
            "length_m": round(arc.length, 1),
        })
    dropped_components = [{
        "bounds_wgs84": [round(v, 6) for v in _project(p, inverse).bounds],
        "area_m2_epsg3310": round(p.area, 1),
    } for p in dropped + cut_dropped]
    cut_arcs.sort(key=lambda a: (a["from_lon_lat"], a["to_lon_lat"], a["mid_lon_lat"], a["length_m"]))
    dropped_components.sort(key=lambda p: (p["bounds_wgs84"], p["area_m2_epsg3310"]))
    shore = shapely.line_merge(water.boundary.difference(frame_ll.boundary))
    return water, {
        "cut_arcs": cut_arcs,
        "components_dropped": dropped_components,
        **_displacement(_project(shore, forward), lines_m, arcs, close_m, inverse),
    }


def to_geojson(geometry: Polygon | MultiPolygon, region: str) -> dict:
    """Return a single-feature RFC 7946 collection for the zone loader."""
    if (not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty
            or shapely.get_coordinate_dimension(geometry) != 2 or not _wgs84(geometry) or not geometry.is_valid):
        raise ValueError("expected a valid, nonempty 2D WGS84 Polygon or MultiPolygon")
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"region_id": region},
        "geometry": mapping(shapely.orient_polygons(geometry)),
    }]}

"""Split regional water using a caller-supplied, reviewed US-waters boundary."""

from hashlib import sha256
import json
from pathlib import Path
from typing import cast

import shapely
from pyproj import Transformer
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry


class BorderError(ValueError):
    """The supplied US-waters boundary is not usable."""


def load_boundary(path: str | Path) -> tuple[Polygon | MultiPolygon, str]:
    """Read a bare WGS84 polygonal GeoJSON geometry and hash its exact bytes.

    This checks the geometry, not the provenance or jurisdiction of the input.
    """
    data = Path(path).read_bytes()
    try:
        doc = json.loads(data)
    except ValueError as exc:
        raise BorderError("invalid boundary JSON") from exc
    if not isinstance(doc, dict) or doc.get("type") not in ("Polygon", "MultiPolygon"):
        raise BorderError("expected a GeoJSON Polygon or MultiPolygon")
    try:
        boundary = shape(doc)
    except (ValueError, KeyError, TypeError, IndexError, GEOSException) as exc:
        raise BorderError("invalid boundary GeoJSON") from exc

    if boundary.is_empty or not boundary.is_valid:
        raise BorderError("expected a nonempty, valid US-waters boundary")
    west, south, east, north = boundary.bounds
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise BorderError("expected WGS84 longitude/latitude coordinates")
    for polygon in shapely.get_parts(boundary):
        for ring in (polygon.exterior, *polygon.interiors):
            coords = ring.coords
            if any(a[0] != b[0] and a[1] != b[1] for a, b in zip(coords, coords[1:])):
                return cast(Polygon | MultiPolygon, boundary), sha256(data).hexdigest()
    raise BorderError("US-waters boundary cannot consist only of axis-aligned edges")


def _project(geometry: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    return shapely.transform(geometry, transformer.transform, interleaved=False)


def _polygonal(geometry: BaseGeometry) -> Polygon | MultiPolygon:
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    # A shared edge or point (possibly alongside polygons) is not water area.
    parts = [part for part in shapely.get_parts(geometry) if isinstance(part, (Polygon, MultiPolygon))]
    return cast(Polygon | MultiPolygon, shapely.union_all(parts)) if parts else Polygon()


def _to_wgs84(geometry: BaseGeometry, inverse: Transformer) -> Polygon | MultiPolygon:
    result = _project(_polygonal(geometry), inverse)
    # Inverse projection of vertices can introduce ring crossings on rejoining them.
    return _polygonal(result if result.is_valid else shapely.make_valid(result))


def clip_to_us(
    water: Polygon | MultiPolygon, boundary: Polygon | MultiPolygon,
) -> tuple[Polygon | MultiPolygon, Polygon | MultiPolygon]:
    """Intersect and subtract in EPSG:3310; return both areas in WGS84."""
    forward = Transformer.from_crs(4326, 3310, always_xy=True)
    inverse = Transformer.from_crs(3310, 4326, always_xy=True)
    water_m = _project(water, forward)
    boundary_m = _project(boundary, forward)
    return (
        _to_wgs84(water_m.intersection(boundary_m), inverse),
        _to_wgs84(water_m.difference(boundary_m), inverse),
    )


def no_survey(outside: Polygon | MultiPolygon) -> dict | None:
    """Return the unsourced no-survey feature, if any outside water remains."""
    if outside.is_empty:
        return None
    return {
        "type": "Feature",
        "geometry": mapping(shapely.orient_polygons(outside)),
        "properties": {"tier": "none", "reason": "outside-us-waters"},
    }

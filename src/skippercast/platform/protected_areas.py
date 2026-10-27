"""Necessary CDFW DS582 query geography checks, without I/O or legal claims."""
from __future__ import annotations

from dataclasses import dataclass
import math
from urllib.parse import parse_qsl, urlsplit

CDFW_SERVICE = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0"
QUERY_SEMANTICS = {
    "where": "1=1", "inSR": "4326", "outSR": "4326",
    "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects",
    "returnGeometry": "true", "f": "geojson",
}


@dataclass(frozen=True)
class SnapshotCoverage:
    covered: bool
    reason: str


class _BindingError(ValueError):
    """A fixed diagnostic, without any provider or private input payload."""


def _require(condition, message):
    if not condition:
        raise _BindingError(message)


def _bounds(value):
    _require(isinstance(value, list) and len(value) == 4
             and all(type(v) in (int, float) and math.isfinite(v) for v in value),
             "Missing or malformed WGS84 query or regional envelope")
    west, south, east, north = value
    _require(-180 <= west < east <= 180 and -90 <= south < north <= 90,
             "Invalid WGS84 query or regional envelope")
    return value


def _boundary_geometry(geometry):
    """Basic GeoJSON ring shape only; no coverage inference or topology claim."""
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return False
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return False
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            return False
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                return False
            for point in ring:
                if (not isinstance(point, list) or len(point) != 2
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                        or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90)):
                    return False
            if ring[0] != ring[-1] or len({tuple(point) for point in ring[:-1]}) < 3:
                return False
    return True


def assess_snapshot_binding(region, snapshot, sources):
    """Check recorded unfiltered query coverage, never counts or polygon extents.

    Accept the collector's comma-separated WGS84 envelope. Unknown parameters
    fail closed: filters and pagination cannot stand in for the whole envelope.
    A pass is neither a freshness receipt nor proof of complete legal boundaries.
    """
    try:
        source = sources.get("cdfw-mpas", {})
        _require("cdfw-mpas" in region.get("source_bindings", {}).get("protected-areas", [])
                 and source.get("review_status") == "approved"
                 and "protected-areas" in source.get("needs", [])
                 and source.get("service_url") == CDFW_SERVICE,
                 "Missing approved CDFW DS582 source binding or endpoint")
        requested = _bounds(region.get("mpa", {}).get("bounds"))
        minimum = region.get("mpa", {}).get("minimum_features")
        _require(type(minimum) is int and minimum >= 1,
                 "Missing or malformed protected-area minimum feature count")
        _require(isinstance(snapshot, dict) and snapshot.get("type") == "FeatureCollection",
                 "Missing or malformed protected-area FeatureCollection")
        _require("region_id" not in snapshot or snapshot["region_id"] == region.get("id"),
                 "Protected-area snapshot belongs to another region")
        # ArcGIS can expose transfer-limit metadata at the top or in properties.
        for metadata in (snapshot, snapshot.get("properties", {})):
            _require(isinstance(metadata, dict), "Malformed protected-area response metadata")
            _require("exceededTransferLimit" not in metadata or metadata["exceededTransferLimit"] is False,
                     "Truncated or ambiguous protected-area response")
        features = snapshot.get("features")
        _require(isinstance(features, list) and len(features) >= minimum,
                 "Insufficient protected-area boundary features")
        for feature in features:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            _require(isinstance(feature, dict) and feature.get("type") == "Feature"
                     and _boundary_geometry(geometry),
                     "Malformed protected-area boundary feature")
        recorded = snapshot.get("source_url")
        _require(isinstance(recorded, str) and bool(recorded),
                 "Missing protected-area source_url query envelope")
        url = urlsplit(recorded)
        _require(not url.fragment and not url.username and not url.password
                 and url._replace(query="").geturl() == source["service_url"] + "/query",
                 "Protected-area source_url does not match the approved DS582 query endpoint")
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        _require(len(query) == len(pairs), "Ambiguous duplicate protected-area query parameters")
        _require(not set(query) - (set(QUERY_SEMANTICS) | {"geometry", "outFields"}),
                 "Filtered, paginated or unsupported protected-area query parameters")
        _require(all(query.get(key) == expected for key, expected in QUERY_SEMANTICS.items()),
                 "Missing or unsupported protected-area envelope query semantics")
        _require("outFields" not in query or bool(query["outFields"].strip()),
                 "Malformed protected-area query fields")
        envelope = _bounds([float(v) for v in query.get("geometry", "").split(",")])
        _require(envelope[0] <= requested[0] and envelope[1] <= requested[1]
                 and envelope[2] >= requested[2] and envelope[3] >= requested[3],
                 "Recorded protected-area query envelope does not contain region.mpa.bounds")
    except _BindingError as error:
        return SnapshotCoverage(False, str(error))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return SnapshotCoverage(False, "Malformed protected-area snapshot binding")
    return SnapshotCoverage(True, "Recorded DS582 query envelope contains region.mpa.bounds; freshness and legal clearance remain separate")

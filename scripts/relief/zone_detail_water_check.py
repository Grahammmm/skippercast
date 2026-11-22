#!/usr/bin/env python3
"""Check saved survey-confidence footprints against the declared mapping zone.

This read-only check uses the producer's existing tiers (including explicit
``none``), not source claims. It measures the union of the outside footprints,
so overlapping detail does not count twice. No zone means no area verdict.
"""

import argparse
import json
import math
from pathlib import Path

import shapely
from pyproj import Transformer
from pyproj.exceptions import ProjError
from shapely.errors import ShapelyError
from shapely.geometry import shape

AREA_CRS = "EPSG:3310"
DEFAULT_AREA_TOLERANCE_M2 = 0.01
TIERS = frozenset({"1m-measured", "2m", "5m", "estimated", "none"})


def _read_collection(path: Path, region: str, role: str):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("type") != "FeatureCollection" or not isinstance(obj.get("features"), list):
        raise ValueError(f"{role}: expected a GeoJSON FeatureCollection")
    if obj.get("region") != region:
        raise ValueError(f"{role}: region does not match the declared region")
    polygons = []
    for i, feature in enumerate(obj["features"]):
        label = f"{role} feature {i}"
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"{label}: expected a GeoJSON Feature")
        if role == "detail":
            props = feature.get("properties")
            tier = props.get("tier") if isinstance(props, dict) else None
            if not isinstance(tier, str) or tier not in TIERS:
                raise ValueError(f"{label}: unknown survey detail tier")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"{label}: expected Polygon or MultiPolygon")
        try:
            polygon = shape(geometry)
        except (KeyError, TypeError, IndexError, ShapelyError) as exc:
            raise ValueError(f"{label}: malformed polygon") from exc
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError(f"{label}: expected valid, nonempty polygon geometry")
        west, south, east, north = polygon.bounds
        if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
            raise ValueError(f"{label}: expected WGS84 longitude/latitude bounds")
        polygons.append(polygon)
    return polygons


def _outside_area_m2(zone, detail) -> float:
    # Overlay in saved GeoJSON coordinates first: reprojecting each input's
    # vertices separately can bend a shared edge differently if only one side
    # subdivides it. Project the resulting outside polygons for the area.
    outside = shapely.union_all(detail).difference(shapely.union_all(zone))
    if outside.is_empty:
        return 0.0
    transform = Transformer.from_crs("EPSG:4326", AREA_CRS, always_xy=True)
    projected = shapely.transform(outside, lambda x, y: transform.transform(x, y, errcheck=True), interleaved=False)
    area = projected.area
    if not math.isfinite(area) or not projected.is_valid:
        raise ValueError("outside footprint could not be measured in EPSG:3310")
    return area


def main(argv=None) -> int:
    """Print a JSON report; exit 0 within tolerance, 1 outside, 2 unknown/invalid."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True, help="region ID declared in both GeoJSON files")
    parser.add_argument("--zone", required=True, type=Path, help="saved zone.geojson")
    parser.add_argument("--detail", required=True, type=Path, help="saved detail.geojson")
    parser.add_argument("--area-tolerance-m2", type=float, default=DEFAULT_AREA_TOLERANCE_M2,
                        help="maximum acceptable outside area in m² (default: %(default)s)")
    args = parser.parse_args(argv)
    if not args.region.strip():
        parser.error("--region must not be blank")
    if not math.isfinite(args.area_tolerance_m2) or args.area_tolerance_m2 < 0:
        parser.error("--area-tolerance-m2 must be finite and nonnegative")

    report = dict(region=args.region, area_crs=AREA_CRS, area_tolerance_m2=args.area_tolerance_m2,
                  status="unknown", outside_area_m2=None)
    try:
        try:
            zone = _read_collection(args.zone, args.region, "zone")
        except FileNotFoundError:
            report["reason"] = "missing_zone"
        else:
            if not zone:
                report["reason"] = "empty_zone"
            else:
                detail = _read_collection(args.detail, args.region, "detail")
                area = _outside_area_m2(zone, detail)
                report["outside_area_m2"] = area
                report["status"] = "outside" if area > args.area_tolerance_m2 else "within_tolerance"
    except (OSError, ValueError, ShapelyError, ProjError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, allow_nan=False))
    return {"within_tolerance": 0, "outside": 1, "unknown": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Measure synthetic border water using explicit, bare WGS84 GeoJSON polygons.

Areas are in square metres (EPSG:3310, matching the border clip). Supplied
support counts only where it overlaps water in both the window and the reviewed
boundary. Without support evidence, neither support area nor the remainder is
known. This is not a jurisdiction or source-rights check.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from pyproj import Transformer
import shapely
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, shape

from skippercast.relief import border


def _load_polygon(path: Path, label: str) -> tuple[Polygon | MultiPolygon, str]:
    data = path.read_bytes()
    try:
        doc = json.loads(data)
        if not isinstance(doc, dict) or doc.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("expected a bare Polygon or MultiPolygon")
        geometry = shape(doc)
    except (IndexError, KeyError, TypeError, ValueError, GEOSException) as exc:
        raise ValueError(f"{label}: invalid GeoJSON geometry") from exc
    if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty or not geometry.is_valid:
        raise ValueError(f"{label}: expected a nonempty, valid Polygon or MultiPolygon")
    west, south, east, north = geometry.bounds
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError(f"{label}: expected WGS84 longitude/latitude coordinates")
    return geometry, sha256(data).hexdigest()


def measure(water_path: Path, window_path: Path, boundary_path: Path, support_path: Path | None) -> dict:
    water, water_hash = _load_polygon(water_path, "water")
    window, window_hash = _load_polygon(window_path, "window")
    boundary, boundary_hash = border.load_boundary(boundary_path)
    inside, _ = border.clip_to_us(water, boundary)
    forward = Transformer.from_crs(4326, 3310, always_xy=True)

    def project(geometry):
        return shapely.transform(geometry, forward.transform, interleaved=False)

    us_water = project(inside).intersection(project(window))
    support_hash = support_m2 = remainder_m2 = None
    if support_path is not None:
        support, support_hash = _load_polygon(support_path, "support")
        # A shared edge or point contributes zero area. Bound float roundoff at full coverage.
        support_m2 = min(us_water.intersection(project(support)).area, us_water.area)
        remainder_m2 = us_water.area - support_m2
    return {
        "us_water_m2": us_water.area,
        "support_m2": support_m2,
        "remainder_m2": remainder_m2,
        "sha256": {"water": water_hash, "support": support_hash, "window": window_hash, "boundary": boundary_hash},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure synthetic border water and support in square metres.")
    for label in ("water", "window", "boundary"):
        parser.add_argument(f"--{label}", required=True, type=Path)
    parser.add_argument("--support", type=Path, help="omit when surveyed-support evidence is unavailable")
    args = parser.parse_args()
    try:
        report = measure(args.water, args.window, args.boundary, args.support)
        output = json.dumps(report, allow_nan=False)
    except (OSError, ValueError, GEOSException) as exc:
        parser.error(str(exc))
    print(output)


if __name__ == "__main__":
    main()

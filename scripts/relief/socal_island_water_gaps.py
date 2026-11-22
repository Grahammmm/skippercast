#!/usr/bin/env python3
"""Report fixture-only water gaps for the two SoCal island subregions.

For each region ID, read <fixture-root>/<id>/water.geojson and
usable-support.geojson as bare 2D WGS84 (longitude, latitude) GeoJSON
Polygon or MultiPolygon objects. A missing water file leaves both areas unknown;
a missing support file leaves only the gap unknown. A present fixture is
an explicit footprint, not evidence outside its polygons. This report does
not determine operational readiness or modify any hold.
"""

import argparse
import json
from pathlib import Path

from pyproj import Transformer
import shapely
from shapely.errors import GEOSException
from shapely.geometry import box, shape

from skippercast.paths import repo_root

REGION_IDS = ("channel-islands-north", "outer-islands-borderland")
AREA_EPSG = 3310


def _read_polygon(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        doc = json.loads(text)
        if not isinstance(doc, dict) or "crs" in doc or doc.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("expected a bare WGS84 Polygon or MultiPolygon")
        polygons = [doc["coordinates"]] if doc["type"] == "Polygon" else doc["coordinates"]
        for polygon in polygons:
            for ring in polygon:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("expected closed GeoJSON rings")
        geom = shape(doc)
        if geom.is_empty or not geom.is_valid or geom.has_z or geom.has_m:
            raise ValueError("expected a nonempty, valid 2D polygon")
        if not all(-180 <= x <= 180 and -90 <= y <= 90 for x, y in shapely.get_coordinates(geom)):
            raise ValueError("expected WGS84 longitude/latitude coordinates")
    except (IndexError, KeyError, TypeError, ValueError, GEOSException) as exc:
        raise ValueError(f"{path.name}: {exc}") from exc
    return geom


def report_water_gaps(fixture_root: Path) -> dict:
    """Read each window independently; return square metres or JSON null."""
    forward = Transformer.from_crs(4326, AREA_EPSG, always_xy=True)

    def area(geometry):
        # Sample long edges before projection so their curvature is not lost.
        dense = shapely.segmentize(geometry, 0.005)
        return shapely.transform(dense, forward.transform, interleaved=False).area

    windows = {}
    for region_id in REGION_IDS:
        config_path = repo_root() / "regions" / region_id / "region.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        west, south, east, north = config["bounds"]
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(f"{region_id}: expected ordered WGS84 bounds")
        fixture_dir = fixture_root / region_id
        water = _read_polygon(fixture_dir / "water.geojson")
        row = {"water_m2": None, "unsupported_water_m2": None}
        if water is not None:
            support = _read_polygon(fixture_dir / "usable-support.geojson")
            # Overlay in fixture coordinates, then measure. This preserves land
            # holes and avoids projecting common edges with different vertices.
            water = water.intersection(box(west, south, east, north))
            row["water_m2"] = area(water)
            if support is not None:
                row["unsupported_water_m2"] = area(water.difference(support))
        windows[region_id] = row
    return {"area_epsg": AREA_EPSG, "windows": windows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fixture_root", type=Path)
    args = parser.parse_args()
    try:
        output = json.dumps(report_water_gaps(args.fixture_root), allow_nan=False)
    except (OSError, ValueError, GEOSException) as exc:
        parser.error(str(exc))
    print(output)


if __name__ == "__main__":
    main()

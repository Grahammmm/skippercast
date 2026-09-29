#!/usr/bin/env python3
"""Compare public CIAP Cruise E video fixes with private 100 m research blocks.

The WFS layer has timecoded video positions, not fish or substrate annotations.
Only aggregate overlap counts leave var/review; no block or video coordinates
enter the public receipt.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "https://data.axds.co/gs/ciap_seafloor/wfs"
LAYER = "ciap_seafloor:cruise_e_videopoints"
BLOCKS = {
    "big-sur-block03": ("var/review/bss03-camera-100m-blocks.geojson", "EPSG:26910", 3),
    "estero": ("var/review/estero-nominal-research-blocks.geojson", "EPSG:32610", 60),
    "point-buchon-rov": ("var/review/point-buchon-rov-100m-blocks.geojson", "EPSG:32610", 26),
    "point-buchon-terrain": ("var/review/point-buchon-2009-csumb-100m-blocks.geojson", "EPSG:32610", 181),
}
OUTPUT = Path("research/receipts/ciap-2016-central-video-private-block-overlap.json")


def load_blocks(path, expected_crs, expected_count):
    data = json.loads(path.read_text())
    if data.get("crs") != expected_crs or len(data.get("features", [])) != expected_count:
        raise ValueError("Private research-block CRS or count changed")
    polygons = [shape(feature["geometry"]) for feature in data["features"]]
    if any(not p.is_valid or p.is_empty or abs(p.area - 10000) > .01 for p in polygons):
        raise ValueError("Private 100 m research-block geometry changed")
    return polygons


def query_bounds(polygons, crs):
    # The 300 m envelope is a bounded download window; it is not a safe route,
    # a fish footprint or the position-error bound for either source.
    envelope = unary_union(polygons).envelope.buffer(300)
    to_geo = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return transform(to_geo.transform, envelope).bounds


def fetch(bounds):
    url = SOURCE + "?" + urlencode({
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "outputFormat": "application/json", "typeName": LAYER,
        "bbox": ",".join(str(n) for n in bounds), "maxFeatures": 10000,
    })
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast source audit/1.0"}), timeout=40) as response:
        if response.status != 200:
            raise ValueError("CIAP video WFS unavailable")
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError("CIAP video WFS bounded response exceeded 20 MB")
    data = json.loads(raw)
    if (data.get("type") != "FeatureCollection"
            or data.get("numberReturned") != len(data.get("features", []))
            or data.get("totalFeatures") != data.get("numberReturned")
            or data.get("numberReturned", 0) >= 10000):
        raise ValueError("CIAP video WFS response truncated or changed")
    return data["features"]


def measure(polygons, crs, features):
    tree = STRtree(polygons)
    project = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    counts = {"inside": 0, "within_100m": 0, "within_250m": 0}
    nearest = None
    line_units = set()
    dive_units = set()
    ids = set()
    for feature in features:
        props = feature.get("properties", {})
        if feature.get("geometry", {}).get("type") != "Point":
            raise ValueError("CIAP video feature geometry changed")
        uid = props.get("id")
        if uid is None or uid in ids:
            raise ValueError("CIAP video feature ID missing or duplicated")
        ids.add(uid)
        lon, lat = props.get("lon"), props.get("lat")
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or not (-125 < lon < -117 and 32 < lat < 39):
            raise ValueError("CIAP video precise position missing or outside Central Coast")
        point = Point(*project.transform(lon, lat))
        distance = polygons[tree.nearest(point)].distance(point)
        nearest = distance if nearest is None else min(nearest, distance)
        counts["inside"] += distance == 0
        counts["within_100m"] += distance <= 100
        counts["within_250m"] += distance <= 250
        if distance <= 250:
            line_units.add((props.get("site"), props.get("dive"), props.get("line")))
            dive_units.add((props.get("site"), props.get("dive")))
    return {
        "downloaded_video_fixes_in_query_window": len(features),
        "nearest_video_fix_to_block_m": round(nearest, 1) if nearest is not None else None,
        "video_fix_counts": counts,
        "distinct_site_dive_line_units_within_250m": len(line_units),
        "distinct_site_dive_units_within_250m": len(dive_units),
    }


def build(root=ROOT):
    groups = {}
    for name, (relative, crs, count) in BLOCKS.items():
        polygons = load_blocks(root / relative, crs, count)
        fixes = fetch(query_bounds(polygons, crs))
        groups[name] = {"research_blocks": count, **measure(polygons, crs, fixes)}
    return {
        "schema_version": 1,
        "scope": "ciap-2016-central-video-to-private-300ft-research-blocks",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_wfs": SOURCE,
        "source_layer": LAYER,
        "source_kind": "timecoded-video-position-not-fish-observation",
        "groups": groups,
        "original_fish_substrate_observation_table_joined": False,
        "video_position_total_error_verified": False,
        "source_depth_and_mllw_qualified": False,
        "independent_substrate_gate_satisfied": False,
        "biological_fish_gate_satisfied": False,
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
        "limitations": "Distances use the WFS precise lon/lat attributes to whole private 100 m research blocks. Nearby frames from a few transect lines are highly correlated; their count is not fish count, independent sampling, bottom-class validation or fishing success. The displayed site/location names are not used for geography. Depth, datum, cleaned-track error, position gaps, fish and substrate annotations, current legal access and full routes remain unverified. A zero within the bounded query means this particular WFS layer has no video fix nearby, not that habitat or fish are absent.",
    }


def stable(report):
    return {key: value for key, value in report.items() if key != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    report = build(args.root)
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("CIAP video/research-block spatial support changed; review before publication")
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("CIAP video overlap checked for four private block groups; zero fishing targets")


if __name__ == "__main__":
    main()

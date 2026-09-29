#!/usr/bin/env python3
"""Test 2010 USGS camera windows against measured 2009 Monterey beam positions.

Historical biological windows and bathymetric soundings are separate surveys.
The nearest-beam distance is a source-alignment diagnostic, never a waypoint.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely.ops import transform as transform_geometry

from research.scripts.audit_monterey_2009_ncei_valid_beams import (
    BASE, PROCESSED, ROOT, decode_line, file_name, read_pinned,
)
from research.scripts.audit_usgs_video_observations import load_archive, open_original_zip
from research.scripts.audit_usgs_native_overlap import camera_accuracy


CRUISE = "s2210mb"
CRUISE_SHA = "48283dc9362a1f3654ec24452f72cb84c25092157f2867d9cb6c060393bb44a6"
CAMERA_BASE = "https://pubs.usgs.gov/ds/781/video_observations/data/"
INTERIOR_M = 25


def build(root, fetch=False):
    beam_path = root / "dist/data/monterey-2009-centralmontereybay-valid-beam-review.json"
    video_path = root / "dist/data/usgs-offshore-monterey-video-overlap.json"
    beam_receipt = json.loads(beam_path.read_text())
    video_receipt = json.loads(video_path.read_text())
    layer = next(row for row in video_receipt["layers"]
                 if row["context_file"] == "usgs-offshore-monterey-hard-context.geojson")
    prior = {row["outline_id"]: row for row in layer["matched_outlines"]}
    if (beam_receipt.get("scope") != "monterey-2009-centralmontereybay-original-valid-beam-research"
            or video_receipt.get("scope") != "usgs-video-vs-native-hard-context-review"
            or video_receipt.get("minimum_interior_clearance_m") != INTERIOR_M):
        raise ValueError("Original beam or camera spatial review changed")
    features = {feature["properties"]["id"]: feature
                for feature in json.loads((root / "dist/data/usgs-offshore-monterey-hard-context.geojson").read_text())["features"]}
    outlines = {suffix: shape(features[row["context_id"]]["geometry"])
                for suffix, row in beam_receipt["outlines"].items()}
    if set(outlines) != {"023", "046"}:
        raise ValueError("Priority Monterey outline set changed")
    positions = defaultdict(lambda: {"lon": [], "lat": []})

    def collect(ident, lon, lat, depth):
        positions[ident]["lon"].append(lon)
        positions[ident]["lat"].append(lat)

    cache = root / "var/review/ncei-centralmontereybay-priority"
    for stem, spec in sorted(PROCESSED.items()):
        name = file_name(stem)
        source = cache / name
        read_pinned(source, BASE + name, spec[1], fetch, 30_000_000)
        companion_base = BASE + "generated/" + name.removesuffix(".gz")
        inf = read_pinned(cache / (name.removesuffix(".gz") + ".inf"), companion_base + ".inf", spec[2], fetch, 1_000_000)
        fnv = read_pinned(cache / (name.removesuffix(".gz") + ".fnv"), companion_base + ".fnv", spec[3], fetch, 2_000_000)
        _, rows, _, _ = decode_line(source, inf, fnv, spec, outlines, collect=collect)
        expected = next(row for row in beam_receipt["lines"] if row["ncei_file_id"] == spec[0])
        if any(rows[ident]["valid_beams_inside_outline"] != expected["outlines"][ident]["valid_beams_inside_outline"] for ident in outlines):
            raise ValueError("NCEI original beam count changed")

    to_m = Transformer.from_crs("EPSG:4326", "EPSG:26910", always_xy=True)
    to_review = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True).transform
    geometry = {ident: transform_geometry(to_review, polygon) for ident, polygon in outlines.items()}
    trees = {}
    for ident in outlines:
        lon, lat = np.concatenate(positions[ident]["lon"]), np.concatenate(positions[ident]["lat"])
        if len(lon) != beam_receipt["outlines"][ident]["valid_beams_inside_outline"]:
            raise ValueError("NCEI original beam outline tally changed")
        x, y = to_m.transform(lon, lat)
        trees[ident] = cKDTree(np.column_stack((x, y)))

    raw = load_archive(root / "var/usgs-video-cache", CRUISE, CRUISE_SHA, CAMERA_BASE, fetch)
    accuracy = camera_accuracy(raw)
    reader = open_original_zip(raw)
    windows = defaultdict(list)
    for item in reader.iterShapeRecords():
        record = item.record.as_dict()
        if not item.shape.points or not record.get("MAJOR_GEO"):
            continue
        lon, lat = item.shape.points[0]
        point = transform_geometry(to_review, Point(lon, lat))
        for ident, polygon in geometry.items():
            if not polygon.contains(point) or polygon.boundary.distance(point) < INTERIOR_M:
                continue
            x, y = to_m.transform(lon, lat)
            distance, _ = trees[ident].query([x, y], k=1)
            windows[ident].append({
                "distance_m": float(distance),
                "rock_bottom": str(record["MAJOR_GEO"]).strip().lower() in {"rock", "boulder", "cobble"},
                "rockfish_positive": bool(record.get("rockfish", 0) > 0),
                "lingcod_positive": bool(record.get("lingcod", 0) > 0),
                "date": str(record.get("Date")),
                "line": str(record.get("LINE")),
            })
    summaries = {}
    for ident in sorted(outlines):
        entries = windows[ident]
        earlier = prior.get(beam_receipt["outlines"][ident]["context_id"])
        if (not earlier or len(entries) != earlier["interior_windows"]
                or sum(row["rock_bottom"] for row in entries) != earlier["rock_boulder_cobble_windows"]
                or sum(row["rockfish_positive"] for row in entries) != earlier["rockfish_positive_windows"]
                or sum(row["lingcod_positive"] for row in entries) != earlier["lingcod_positive_windows"]):
            raise ValueError("Historical USGS camera window interpretation changed")
        distances = np.array([row["distance_m"] for row in entries])
        summaries[ident] = {
            "context_id": beam_receipt["outlines"][ident]["context_id"],
            "interior_camera_windows": len(entries),
            "rock_boulder_cobble_windows": sum(row["rock_bottom"] for row in entries),
            "rockfish_positive_windows": sum(row["rockfish_positive"] for row in entries),
            "lingcod_positive_windows": sum(row["lingcod_positive"] for row in entries),
            "distinct_camera_transects": len({(row["date"], row["line"]) for row in entries}),
            "observation_dates": sorted({row["date"] for row in entries}),
            "nearest_valid_2009_beam_distance_m_range": [round(float(distances.min()), 2), round(float(distances.max()), 2)],
            "nearest_valid_2009_beam_distance_m_median": round(float(np.median(distances)), 2),
            "camera_windows_with_valid_2009_beam_within_2m": int((distances <= 2).sum()),
            "camera_windows_with_valid_2009_beam_within_10m": int((distances <= 10).sum()),
            "rockfish_positive_windows_with_beam_within_10m": sum(row["rockfish_positive"] and row["distance_m"] <= 10 for row in entries),
            "independent_current_fish_presence_qualified": False,
            "fishing_target": False, "exportable": False,
        }
    return {
        "schema_version": 1, "scope": "monterey-2009-beam-to-2010-video-proximity-research",
        "original_beam_receipt_sha256": hashlib.sha256(beam_path.read_bytes()).hexdigest(),
        "original_camera_receipt_sha256": hashlib.sha256(video_path.read_bytes()).hexdigest(),
        "usgs_camera_archive_url": CAMERA_BASE + CRUISE + "_video_observations.zip",
        "usgs_camera_archive_sha256": CRUISE_SHA,
        "camera_position_accuracy_report": accuracy,
        "minimum_outline_interior_clearance_m": INTERIOR_M,
        "outlines": summaries, "fishing_target": False, "exportable": False,
        "limitations": [
            "Camera windows were recorded in 2010 and are not present-day fish occurrence or catch-rate evidence. Consecutive windows on one transect are correlated.",
            "The original USGS camera metadata calls positions highly variable on the order of 10 m; a nearest-beam distance is not an independently verified bottom-camera footprint or registration bound.",
            "The 2009 beam survey and 2010 camera are separate acquisitions, but both may contribute to later USGS/NOAA interpretations. This proximity audit does not establish independent gridded depth, MLLW, uncertainty or legal access.",
            "No original beam coordinates, camera positions or fishing waypoints are published.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/data/monterey-2009-beam-2010-video-proximity.json"))
    args = parser.parse_args()
    report = build(args.root.resolve(), args.fetch)
    if args.verify:
        previous = json.loads(args.verify.read_text())
        if report != {key: value for key, value in previous.items() if key != "checked_at"}:
            raise ValueError("Original beam-to-video review changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("Original 2009 Monterey beams paired with 2010 USGS camera windows; zero fishing targets")


if __name__ == "__main__":
    main()

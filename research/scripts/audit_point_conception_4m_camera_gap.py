#!/usr/bin/env python3
"""Measure original USGS camera proximity to the two private 4 m research patches.

Public output contains aggregate distances only. Nearby transect frames are not
independent patch observations, current fish presence, or fishing waypoints.
"""

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point
from shapely.ops import transform

from research.scripts.audit_point_conception_4m_access import candidate_footprints
from research.scripts.audit_point_conception_4m_hard_overlap import USGS_CACHE
from research.lib.paths import ROOT
from research.scripts.audit_point_conception_original_300_gap import CACHE
from research.scripts.audit_usgs_native_overlap import camera_accuracy
from research.scripts.audit_usgs_video_observations import load_archive, open_original_zip


OUTPUT = ROOT / "research/receipts/point-conception-original-4m-camera-gap.json"
MANIFEST = ROOT / "research/catalog/usgs-video-cruises.json"
PRIOR = ROOT / "dist/data/point-conception-original-4m-rugged-overlap.json"


def audit(manifest, video_cache, candidates, *, download=False):
    to_native = Transformer.from_crs(4326, 26910, always_xy=True).transform
    records = {survey: [] for survey, _, _ in candidates}
    sources = []
    for cruise, sha in sorted(manifest["archives"].items()):
        raw = load_archive(video_cache, cruise, sha, manifest["base_url"], download)
        accuracy = camera_accuracy(raw)
        reader = open_original_zip(raw)
        sources.append({"cruise": cruise, "sha256": sha,
                        "url": manifest["base_url"] + cruise + "_video_observations.zip",
                        "records": len(reader), "position_accuracy_note": accuracy})
        for item in reader.iterShapeRecords():
            if not item.shape.points:
                continue
            point = transform(to_native, Point(*item.shape.points[0]))
            row = item.record.as_dict()
            observed = str(row.get("MAJOR_GEO") or "").strip().lower()
            survey_date = row.get("Date_")
            for survey, _, footprint in candidates:
                distance = footprint.distance(point)
                if distance <= 1000:
                    records[survey].append((distance, cruise, observed,
                                            survey_date.isoformat() if isinstance(survey_date, date) else None,
                                            str(row.get("LINE") or "unknown"),
                                            int(row.get("rockfish") or 0) > 0,
                                            int(row.get("lingcod") or 0) > 0))
    rows = []
    for survey, cells, _ in candidates:
        nearby = records[survey]
        within_250 = [item for item in nearby if item[0] <= 250 and item[2]]
        inside = [item for item in nearby if item[0] == 0 and item[2]]
        minimum = min((item[0] for item in nearby), default=None)
        rows.append({
            "survey_id": survey,
            "component_area_m2": cells * 16,
            "nearest_camera_window_within_1000m_m": round(minimum, 1) if minimum is not None else None,
            "bottom_observations_inside_component": len(inside),
            "bottom_observations_within_250m": len(within_250),
            "bottom_observations_within_1000m": sum(bool(item[2]) for item in nearby),
            "within_250m_bottom_classes": dict(sorted(Counter(item[2] for item in within_250).items())),
            "within_250m_rockfish_positive_windows": sum(item[5] for item in within_250),
            "within_250m_lingcod_positive_windows": sum(item[6] for item in within_250),
            "within_250m_distinct_transects": len({(item[1], item[3], item[4]) for item in within_250}),
            "within_250m_cruises": sorted({item[1] for item in within_250}),
            "within_250m_observation_dates": sorted({item[3] for item in within_250 if item[3]}),
            "camera_verified_bottom": False,
            "fishing_target": False,
            "exportable": False,
        })
    return {
        "schema_version": 1,
        "scope": "point-conception-two-original-4m-components-usgs-video-proximity",
        "catalog_url": manifest["catalog_url"],
        "distance_crs": "EPSG:26910",
        "sources": sources,
        "components": rows,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "The entire pinned USGS DS 781 cruise catalog was searched; source coverage does not imply camera coverage at either patch.",
            "USGS camera horizontal accuracy is highly variable, on the order of 10 m. A nearby window does not verify a different patch 100–250 m away.",
            "Consecutive video windows on one line are one transect, not independent surveys. Fish codes are historical visual observations, not catch or present abundance.",
            "No research patch geometry, chartplotter waypoint or fishing rank is published.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--video-cache", type=Path, default=ROOT / "var/usgs-video-cache")
    parser.add_argument("--bag-cache", type=Path, default=CACHE)
    parser.add_argument("--usgs-cache", type=Path, default=USGS_CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--download-missing", action="store_true")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    candidates = candidate_footprints(args.bag_cache, args.usgs_cache, json.loads(PRIOR.read_text()))
    result = audit(json.loads(args.manifest.read_text()), args.video_cache, candidates,
                   download=args.download_missing)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception original camera proximity changed; hold for review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"components": len(result["components"]),
                      "camera_verified": sum(row["camera_verified_bottom"] for row in result["components"])}))


if __name__ == "__main__":
    main()

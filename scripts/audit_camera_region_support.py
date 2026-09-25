"""Count reviewed original camera windows inside one exact regional package.

Survey envelopes can intersect adjacent regions even when every observed camera
window is elsewhere. Publish only archive identities and grouped counts, never
camera coordinates or an inferred fishing area.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.audit_usgs_video_observations import open_original_zip
from skippercast.platform.contracts import REPO, atomic_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(region_id, survey_id, pairs_path, camera_cache, *, root=REPO):
    root = Path(root)
    region_path = root / "regions" / region_id / "region.json"
    region = json.loads(region_path.read_text())
    if region.get("id") != region_id or region.get("status") == "draft":
        raise ValueError("Expected an exact published or preview region")
    west, south, east, north = region["fishing_bounds"]
    if not -125 <= west < east <= -116 or not 32 <= south < north <= 42:
        raise ValueError("Invalid California fishing bounds")
    pairs = json.loads(Path(pairs_path).read_text())
    if pairs.get("scope") != "statewide-original-camera-regular-bag-discovery-review":
        raise ValueError("Original BAG/camera pair review is missing")
    selected = [p for p in pairs["pair_reviews"] if p.get("survey_id") == survey_id]
    if not selected or not all(p.get("report_hazard_review_complete") for p in selected):
        raise ValueError("No report-reviewed original camera pairs for survey")
    readers = {}
    receipts = {}
    unique = set()
    rows = []
    for pair in selected:
        cruise = pair["cruise"]
        url = pair["camera_archive_url"]
        if url != ("https://pubs.usgs.gov/ds/781/video_observations/data/"
                   + cruise + "_video_observations.zip"):
            raise ValueError("Camera archive URL is not the reviewed USGS original")
        if cruise not in readers:
            archive = Path(camera_cache) / (cruise + "_video_observations.zip")
            digest = sha(archive)
            if digest != pair["camera_archive_sha256"]:
                raise ValueError("Original USGS camera archive changed")
            readers[cruise] = open_original_zip(archive.read_bytes())
            receipts[cruise] = {"url": url, "sha256": digest}
        elif receipts[cruise]["sha256"] != pair["camera_archive_sha256"]:
            raise ValueError("Conflicting archive identities for the same cruise")
        for transect in pair["transects"]:
            indices = transect["camera_record_indices"]
            if len(indices) != transect["window_count"]:
                raise ValueError("Reviewed transect camera count changed")
            local = 0
            novel = 0
            for index in indices:
                identity = (cruise, index)
                if identity in unique:
                    continue
                unique.add(identity)
                novel += 1
                points = readers[cruise].shape(index).points
                if len(points) != 1:
                    raise ValueError("Expected an original camera point")
                longitude, latitude = points[0]
                if not -125 <= longitude <= -116 or not 32 <= latitude <= 42:
                    raise ValueError("Original camera coordinates are outside California")
                local += int(west <= longitude <= east and south <= latitude <= north)
            rows.append({"cruise": cruise, "bag_url": pair["bag_url"],
                         "line": transect["line"], "date": transect["date"],
                         "reviewed_pair_windows": len(indices),
                         "new_distinct_windows": novel, "windows_inside_region": local})
    return {"schema_version": 1, "scope": "original-camera-regional-support-review",
            "region_id": region_id, "survey_id": survey_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "region_sha256": sha(region_path), "pair_review_sha256": sha(pairs_path),
            "source_archives": receipts, "reviewed_pairs": len(selected),
            "distinct_camera_windows": len(unique),
            "windows_inside_region": sum(row["windows_inside_region"] for row in rows),
            "transects": rows, "fishing_target": False, "exportable": False,
            "limitations": "Historical camera positions are approximate and correlated along transects. This is an exact regional source-relevance test, not a mapped reef, present fish record, safe route, legal clearance or catch forecast."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--survey", required=True)
    parser.add_argument("--pairs", type=Path, default=Path("dist/data/noaa-statewide-regular-camera-review.json"))
    parser.add_argument("--camera-cache", type=Path, default=Path("var/usgs-video-cache"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path, help="Fail when the pinned public review changes")
    args = parser.parse_args()
    result = audit(args.region, args.survey, args.pairs, args.camera_cache)
    if args.verify:
        baseline = json.loads(args.verify.read_text())
        comparable = lambda record: {k: v for k, v in record.items() if k != "reviewed_at"}
        if comparable(result) != comparable(baseline):
            raise ValueError("Regional original-camera source relevance changed; review before publication")
    atomic_json(args.output, result)
    print(json.dumps({"survey": args.survey, "distinct_camera_windows": result["distinct_camera_windows"],
                      "windows_inside_region": result["windows_inside_region"]}))


if __name__ == "__main__":
    main()

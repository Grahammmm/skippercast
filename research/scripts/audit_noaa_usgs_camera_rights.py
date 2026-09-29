"""Pin official NOAA/USGS rights and use conditions for a survey/camera pair.

This is a source-rights receipt, not approval of geometry, navigation or fishing.
The original pages are fetched each run; changed text fails baseline verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

from skippercast.platform.contracts import atomic_json


def fetch(url):
    if not (url.startswith("https://www.ngdc.noaa.gov/nos/")
            or url.startswith("https://pubs.usgs.gov/ds/781/video_observations/metadata/")):
        raise ValueError("Rights document is outside the reviewed NOAA/USGS hosts")
    request = urllib.request.Request(url, headers={"User-Agent": "SkipperCast source-rights review/1.0"})
    with urllib.request.urlopen(request, timeout=35) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("Official rights document moved or failed")
        raw = response.read(1_000_001)
    if not raw or len(raw) > 1_000_000:
        raise ValueError("Rights document is empty or exceeds bounded review size")
    return raw


def audit(survey_id, cruise, noaa_raw, usgs_raw):
    noaa = noaa_raw.decode("utf-8", "replace")
    usgs = usgs_raw.decode("utf-8", "replace")
    if (survey_id not in noaa
            or "Creative Commons Zero 1.0 Universal Public Domain Dedication (CC0-1.0)" not in noaa
            or "NOAA waives any potential copyright" not in noaa
            or cruise.upper() + "_video_observations" not in usgs
            or "Access_Constraints: None" not in usgs
            or "This information is not intended for navigational purposes." not in usgs
            or "Acknowledge the U.S. Geological Survey in products derived from these data." not in usgs
            or "Share data products developed using these data with the U.S. Geological Survey." not in usgs):
        raise ValueError("Official source identity or use conditions changed")
    return {"schema_version": 1, "scope": "noaa-usgs-original-camera-source-rights",
            "survey_id": survey_id, "camera_cruise": cruise,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "noaa_survey_url": f"https://www.ngdc.noaa.gov/nos/H10001-H12000/{survey_id}.html",
            "noaa_survey_sha256": hashlib.sha256(noaa_raw).hexdigest(),
            "usgs_camera_metadata_url": ("https://pubs.usgs.gov/ds/781/video_observations/metadata/"
                                         + cruise + "_video_observations_metadata.txt"),
            "usgs_camera_metadata_sha256": hashlib.sha256(usgs_raw).hexdigest(),
            "noaa_bag_rights": "NOAA CC0-1.0 dedication",
            "usgs_camera_rights": "USGS-published data; no access constraint",
            "use_conditions": ["Credit the U.S. Geological Survey in derived products",
                               "Share derived data products with the U.S. Geological Survey",
                               "Do not use these source data for navigation",
                               "Respect the camera source's spatial resolution"],
            "fishing_target": False, "exportable": False,
            "limitations": "This verifies published source terms only. It does not establish a current chart, precise camera footprint, safe route, legal take or fish presence today."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", required=True)
    parser.add_argument("--cruise", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.survey != "H11971" or args.cruise != "c210nc":
        raise ValueError("This reviewed binding currently covers H11971/c210nc only")
    noaa_url = f"https://www.ngdc.noaa.gov/nos/H10001-H12000/{args.survey}.html"
    usgs_url = ("https://pubs.usgs.gov/ds/781/video_observations/metadata/"
                + args.cruise + "_video_observations_metadata.txt")
    result = audit(args.survey, args.cruise, fetch(noaa_url), fetch(usgs_url))
    if args.verify:
        baseline = json.loads(args.verify.read_text())
        normalized = lambda row: {key: value for key, value in row.items() if key != "checked_at"}
        if normalized(result) != normalized(baseline):
            raise ValueError("Official source-rights content changed; re-review before using")
    atomic_json(args.output, result)
    print(json.dumps({"survey": args.survey, "camera_cruise": args.cruise,
                      "noaa_cc0": True, "usgs_credit_and_share": True}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Screen Point Conception research polygons against a dated USCG launch BNM.

This is a conservative, time-limited research hold. It does not replace live
USCG broadcasts, chart review or the remaining fishing-promotion gates.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import transform


URL = "https://www.navcen.uscg.gov/broadcast-notice-to-mariners-message?guid=70014340"
SHORTLIST = {"native-hard-H11952-689", "native-hard-H11953-1",
             "native-hard-H11952-604", "native-hard-H11952-1762"}
TIME = re.compile(r"(\d{2})(\d{2})(\d{2})Z\s+([A-Z]{3})\s+TO\s+"
                  r"(\d{2})(\d{2})(\d{2})Z\s+([A-Z]{3})\s+(\d{4})")
DMS = re.compile(r"(\d{1,2})°\s*(\d{1,2})'\s*(\d{1,2})\"\s*N\s+"
                 r"(\d{1,3})°\s*(\d{1,2})'\s*(\d{1,2})\"\s*W")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "h1", "h2"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_text(raw):
    parser = PlainText()
    parser.feed(raw.decode("utf-8"))
    return "".join(parser.parts)


def instant(groups, year):
    day, hour, minute, month = groups
    return datetime.strptime(f"{year} {month} {day} {hour} {minute}",
                             "%Y %b %d %H %M").replace(tzinfo=timezone.utc).isoformat()


def parse_window(text, number):
    marker = f"{number}. HAZARDOUS WINDOW - {number}"
    if marker not in text:
        raise ValueError(f"Notice lacks hazardous window {number}")
    section = text.split(marker, 1)[1]
    if number == 1:
        section = section.split("2. HAZARDOUS WINDOW - 2", 1)[0]
    else:
        section = section.split("3. SURFACE VESSELS", 1)[0]
    area = section.split("HAZARD AREA - 1", 1)[1].split("TO BEGINNING", 1)[0]
    dms = DMS.findall(area)
    if len(dms) < 3:
        raise ValueError("Hazard polygon has too few primary DMS vertices")
    vertices = []
    for lat_d, lat_m, lat_s, lon_d, lon_m, lon_s in dms:
        vertices.append((-(int(lon_d) + int(lon_m) / 60 + int(lon_s) / 3600),
                         int(lat_d) + int(lat_m) / 60 + int(lat_s) / 3600))
    polygon = Polygon(vertices)
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError("Invalid primary USCG hazard polygon")
    windows = []
    for match in TIME.finditer(section):
        values = match.groups()
        start = instant(values[:4], values[8])
        end = instant(values[4:8], values[8])
        if start >= end:
            raise ValueError("USCG window end is not after start")
        windows.append({"start_utc": start, "end_utc": end})
    if len(windows) < 1:
        raise ValueError("USCG hazard notice has no parseable active windows")
    return polygon, windows


def audit(raw, context, queue):
    text = html_text(raw)
    if "SEC LALB BNM 0239-26" not in text or "VANDENBERG SFB" not in text:
        raise ValueError("Unexpected USCG notice identity")
    if queue.get("research_shortlist_count") != 4 or {
        row["context_id"] for row in queue["research_shortlist"]
    } != SHORTLIST:
        raise ValueError("Point Conception shortlist changed")
    features = {f["properties"]["id"]: f for f in context["features"]}
    if not SHORTLIST.issubset(features):
        raise ValueError("Shortlist geometry missing")
    polygons = [parse_window(text, i) for i in (1, 2)]
    to_m = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    areas = [transform(to_m, polygon) for polygon, _ in polygons]
    overlaps = []
    for row in queue["research_shortlist"]:
        ident = row["context_id"]
        geometry = transform(to_m, shape(features[ident]["geometry"]))
        hit = [i + 1 for i, area in enumerate(areas) if area.buffer(100).intersects(geometry)]
        overlaps.append({"context_id": ident, "hazard_window_ids_with_100m_margin": hit,
                         "currently_exportable": False})
    return {"schema_version": 1, "scope": "point-conception-dated-launch-hazard-screen",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source_url": URL, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "notice_id": "SEC LALB BNM 0239-26",
            "notice_cancellation_or_update_checked": False,
            "source_status": "individual USCG message inspected; later cancellation/update requires separate live check",
            "review_buffer_m": 100,
            "hazard_areas": [{"id": i + 1, "vertex_count": len(polygon.exterior.coords) - 1,
                              "windows": windows} for i, (polygon, windows) in enumerate(polygons)],
            "research_shortlist": overlaps,
            "fishing_target": False, "exportable": False,
            "limitations": ["Temporary launch hazard applies only at the stated UTC windows and may be updated or cancelled.",
                            "All four research polygons remain unpromoted for independent chart, access, source-age, fish and route review.",
                            "A BNM is not a substitute for current USCG broadcasts or a navigation chart."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--context", type=Path,
                        default=Path("dist/data/point-conception-native-hard-context.geojson"))
    parser.add_argument("--queue", type=Path,
                        default=Path("dist/data/point-conception-regular-site-review-queue.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.html:
        raw = args.html.read_bytes()
    else:
        with urlopen(Request(URL, headers={"User-Agent": "SkipperCast hazard-source-audit/1.0"}), timeout=25) as response:
            if response.status != 200:
                raise ValueError("USCG notice unavailable")
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("USCG notice unexpectedly large")
    result = audit(raw, json.loads(args.context.read_text()), json.loads(args.queue.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print({row["context_id"]: row["hazard_window_ids_with_100m_margin"]
           for row in result["research_shortlist"]})


if __name__ == "__main__":
    main()

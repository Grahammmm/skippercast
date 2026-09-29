#!/usr/bin/env python3
"""Test NOAA SH-18-09 occurrence points against W00614's measured-cell envelope.

The coral database omits fish and zero-observation effort. This is an
exclusion screen, not a fish-presence, substrate, or target qualification.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen


DATASET = "NOAA_GFNMS_CBNMS_SH-18-09"
DASHBOARD = f"https://www.ncei.noaa.gov/waf/dsc-data/dashboards/{DATASET}.html"
FIELDS = ("DatasetID,CatalogNumber,latitude,longitude,DepthInMeters,Locality,"
          "Substrate,Habitat,ObservationDate,SampleID,EventID,LocationAccuracy,"
          "NavType,RecordType")
SOURCE = ("https://www.ncei.noaa.gov/erddap/tabledap/deep_sea_corals.csv?"
          f"{FIELDS}&DatasetID=%22{DATASET}%22")
DEPTH = Path("dist/data/w00614-original-300-pigeon-monterey-review.json")
USGS_GAP = Path("dist/data/w00614-usgs-video-observation-gap.json")
OUTPUT = Path("dist/data/w00614-noaa-sh1809-observation-gap.json")


def fetch():
    with urlopen(Request(SOURCE, headers={"User-Agent": "SkipperCast source audit/1.0"}),
                 timeout=90) as response:
        if response.status != 200:
            raise ValueError("NOAA ERDDAP occurrence response was not successful")
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("NOAA occurrence response exceeded the review bound")
    return raw


def point_to_rectangle_m(lon, lat, bounds):
    """Approximate short-distance rejection screen, never a position-error model."""
    west, south, east, north = bounds
    dx = (lon - min(max(lon, west), east)) * 111_320 * math.cos(math.radians(lat))
    dy = (lat - min(max(lat, south), north)) * 111_320
    return math.hypot(dx, dy)


def build(raw, depth, usgs_gap):
    if (depth.get("survey_id") != "W00614"
            or depth.get("vertical_datum") != "MLLW"
            or depth.get("counts", {}).get("depth_uncertainty_qualified_200_300ft_cells") != 141331
            or usgs_gap.get("bag_sha256") != depth.get("source_sha256")
            or usgs_gap.get("qualified_cells") != 141331):
        raise ValueError("W00614 original depth lineage changed")
    bounds = usgs_gap["qualified_cell_center_envelope_wgs84"]
    if len(bounds) != 4 or not (bounds[0] < bounds[2] and bounds[1] < bounds[3]):
        raise ValueError("W00614 qualifying-cell envelope changed")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != FIELDS.split(","):
        raise ValueError("NOAA occurrence schema changed")
    rows = list(reader)
    if not rows or rows[0]["DatasetID"] != "" or rows[0]["latitude"] != "degrees_north":
        raise ValueError("NOAA ERDDAP units row changed")
    rows = rows[1:]
    if not rows or any(row["DatasetID"] != DATASET for row in rows):
        raise ValueError("NOAA occurrence dataset selection changed")
    counts = Counter()
    locality = Counter()
    pigeon = []
    distances = []
    near_100 = 0
    near_500 = 0
    for row in rows:
        lon, lat = float(row["longitude"]), float(row["latitude"])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("NOAA occurrence position is invalid")
        distance = point_to_rectangle_m(lon, lat, bounds)
        distances.append(distance)
        near_100 += distance <= 100
        near_500 += distance <= 500
        counts[row["RecordType"]] += 1
        locality[row["Locality"]] += 1
        if "Pigeon" in row["Locality"]:
            pigeon.append(row)
    if not pigeon:
        raise ValueError("Pigeon Point NOAA occurrence locality disappeared")
    if min(distances) <= 100:
        raise ValueError("NOAA ROV occurrences now need an exact W00614 cell/position join")
    position_terms = Counter(row["LocationAccuracy"] for row in pigeon)
    nav_terms = Counter(row["NavType"] for row in pigeon)
    dates = sorted({row["ObservationDate"] for row in pigeon})
    depths = [float(row["DepthInMeters"]) for row in pigeon if row["DepthInMeters"]]
    return {
        "schema_version": 1,
        "scope": "w00614-noaa-sh1809-coral-sponge-observation-gap",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_url": SOURCE,
        "dashboard_url": DASHBOARD,
        "dashboard_database_version_at_review": "20260416-1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_rows": len(rows),
        "record_types": dict(sorted(counts.items())),
        "depth_receipt": str(DEPTH),
        "depth_bag_sha256": depth["source_sha256"],
        "qualified_w00614_cells": 141331,
        "qualified_cell_center_envelope_wgs84": bounds,
        "pigeon_point_locality_rows": len(pigeon),
        "pigeon_point_unique_record_positions": len({(r["longitude"], r["latitude"]) for r in pigeon}),
        "pigeon_point_observation_dates": dates,
        "pigeon_point_depth_range_m": [min(depths), max(depths)],
        "pigeon_point_rows_in_200_300ft_depth_band": sum(60.96 <= d <= 91.44 for d in depths),
        "pigeon_point_location_accuracy_terms": dict(sorted(position_terms.items())),
        "pigeon_point_nav_terms": dict(sorted(nav_terms.items())),
        "points_in_qualified_cell_center_envelope": sum(
            bounds[0] <= float(r["longitude"]) <= bounds[2]
            and bounds[1] <= float(r["latitude"]) <= bounds[3] for r in rows),
        "points_within_100m_of_envelope": near_100,
        "points_within_500m_of_envelope": near_500,
        "approx_nearest_point_to_envelope_m": round(min(distances)),
        "independent_substrate_gate_satisfied": False,
        "biological_fish_gate_satisfied": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": ("The dataset contains coral/sponge occurrence records, not fish observations, "
                        "full ROV transects or zero-observation effort. None falls within 100 m "
                        "of W00614's eligible-cell rectangle. The approximate rectangle "
                        "distance is a rejection screen only; it cannot establish absence "
                        "of rock, fish, coral or sponge, or qualify a fishing waypoint."),
    }


def stable(report):
    return {key: value for key, value in report.items() if key != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Previously fetched exact NOAA CSV")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes() if args.input else fetch()
    report = build(raw, json.loads(DEPTH.read_text()), json.loads(USGS_GAP.read_text()))
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("NOAA SH-18-09 source or W00614 overlap changed; review before promotion")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['source_rows']} NOAA occurrences; nearest {report['approx_nearest_point_to_envelope_m']} m; zero W00614 overlaps")


if __name__ == "__main__":
    main()

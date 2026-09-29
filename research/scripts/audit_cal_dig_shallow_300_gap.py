#!/usr/bin/env python3
"""Verify whether original Cal DIG I ROV annotations support <=300 ft spots.

An observation depth is a source field, not a chart-datum qualification.
This intentionally audits the original point tables, not inferred polygon
classes or bounding-box intersection.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen


BASE = "https://cmgds.marine.usgs.gov/data-releases/media/2021/10.5066-P9QQZ27U/"
SOURCES = {
    "biotic": BASE + "8676dd1cde47458caefd834bb3ed8a87/Cal_DIG_I_Biotic_Component.csv",
    "substrate": BASE + "4334f486b0ae492697ee8215f6515f6f/Cal_DIG_I_Substrate_Component.csv",
}
OUTPUT = Path("dist/data/cal-dig-i-original-rov-300ft-gap.json")


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast source audit/1.0"}), timeout=120) as response:
        raw = response.read(12_000_001)
    if len(raw) > 12_000_000:
        raise ValueError("Cal DIG I observation table exceeded review bound")
    return raw


def summarize(raw, kind):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), skipinitialspace=True)
    if not reader.fieldnames or not {"depth_mete", "Longitude", "Latitude", "video_sequ"}.issubset(reader.fieldnames):
        raise ValueError(f"Cal DIG I {kind} schema changed")
    if kind == "biotic" and "concept" not in reader.fieldnames:
        raise ValueError("Cal DIG I biotic concept field missing")
    if kind == "substrate" and "Induration" not in reader.fieldnames:
        raise ValueError("Cal DIG I substrate class field missing")
    rows = list(reader)
    depths = []
    in_band = 0
    missing_depth = 0
    invalid_negative = 0
    for row in rows:
        lat, lon = float(row["Latitude"]), float(row["Longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Cal DIG I {kind} invalid position")
        if not row["depth_mete"]:
            missing_depth += 1
            continue
        depth = float(row["depth_mete"])
        if depth < 0:
            invalid_negative += 1
            continue
        depths.append(depth)
        in_band += 60.96 <= depth <= 91.44
    if not rows or not depths:
        raise ValueError(f"Cal DIG I {kind} observations missing")
    if in_band:
        raise ValueError(f"Cal DIG I {kind} now has 200–300 ft observations; spatial review required")
    return {
        "source_url": SOURCES[kind],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(rows),
        "missing_depth_rows": missing_depth,
        "negative_depth_rows_excluded": invalid_negative,
        "minimum_nonnegative_observation_depth_m": min(depths),
        "maximum_nonnegative_observation_depth_m": max(depths),
        "observations_in_200_300ft_depth_band": in_band,
    }


def build(biotic, substrate):
    return {
        "schema_version": 1,
        "scope": "cal-dig-i-original-rov-200-300ft-observation-gap",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "release_url": "https://cmgds.marine.usgs.gov/data-releases/datarelease/10.5066-P9QQZ27U/",
        "depth_band_m": [60.96, 91.44],
        "sources": {"biotic": summarize(biotic, "biotic"), "substrate": summarize(substrate, "substrate")},
        "independent_substrate_gate_satisfied": False,
        "biological_fish_gate_satisfied": False,
        "fishing_target": False,
        "exportable": False,
        "limitation": "The original ROV point tables contain no observations in 200–300 ft. The 2026 derived CMECS polygons, if they cover additional depths, are not independent shallow-water video groundtruth; their metadata state substrate accuracy diminishes away from transects and is unquantified. Negative source depths were excluded as invalid, not interpreted as shallow observations. No conclusion about actual fish or habitat absence follows.",
    }


def stable(report):
    return {k: v for k, v in report.items() if k != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--biotic", type=Path)
    parser.add_argument("--substrate", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    report = build(args.biotic.read_bytes() if args.biotic else fetch(SOURCES["biotic"]),
                   args.substrate.read_bytes() if args.substrate else fetch(SOURCES["substrate"]))
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("Cal DIG I point sources changed; review before promoting")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("Cal DIG I: zero original ROV observations in 200–300 ft")


if __name__ == "__main__":
    main()

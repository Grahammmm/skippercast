#!/usr/bin/env python3
"""Audit OPC DataONE ROV fish-count table for 200–300 ft spot-level use.

The file is a historical California mid-depth ROV analysis product. Its source
coordinates and sampling units must be evaluated before any map promotion.
This report deliberately publishes aggregates, never individual ROV fixes.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path


PACKAGE = "https://opc.dataone.org/view/urn:uuid:7353f779-b722-4064-8074-3e9c651ed38e"
OBJECT = "https://cn.dataone.org/cn/v2/resolve/urn%3Auuid%3Abc58965f-f3b1-421e-8b2a-45690bb695fb"
OUTPUT = Path("research/receipts/central-dataone-rov-300ft-spot-precision.json")
FIELDS = ["Year", "Month", "Day", "Region", "MPA_Group", "Type", "Designation", "Habitat_Type", "Lat", "Long", "Depth", "Common_Name", "Scientific_Name", "Count"]
BAND = (Decimal("60.96"), Decimal("91.44"))


def decimal_places(value):
    return max(0, -Decimal(value).as_tuple().exponent)


def build(source_path, min_rows=1_000_000):
    source_path = Path(source_path)
    digest = hashlib.sha256()
    with source_path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    total = 0
    zeros = 0
    central_band = 0
    missing_depth = 0
    units = {}
    unit_years = Counter()
    reference_detections = {"lingcod": set(), "rockfish_group": set()}
    coord_precision = Counter()
    fractional_positive = 0
    with source_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError("OPC DataONE fish count schema changed")
        for row in reader:
            total += 1
            count = Decimal(row["Count"])
            zeros += count == 0
            if row["Region"] != "Central":
                continue
            try:
                depth = Decimal(row["Depth"])
            except InvalidOperation:
                missing_depth += 1
                continue
            if not BAND[0] <= depth <= BAND[1]:
                continue
            central_band += 1
            if not (Decimal("-90") <= Decimal(row["Lat"]) <= Decimal("90")
                    and Decimal("-180") <= Decimal(row["Long"]) <= Decimal("180")):
                raise ValueError("OPC DataONE position invalid")
            coord_precision[(decimal_places(row["Lat"]), decimal_places(row["Long"]))] += 1
            fractional_positive += count > 0 and count != count.to_integral_value()
            key = tuple(row[k] for k in ("Year", "Month", "Day", "MPA_Group", "Type", "Designation", "Habitat_Type", "Lat", "Long", "Depth"))
            if key not in units:
                units[key] = 0
                unit_years[row["Year"]] += 1
            units[key] += 1
            if row["Designation"] == "Reference" and count > 0:
                name = row["Common_Name"].casefold()
                if name == "lingcod":
                    reference_detections["lingcod"].add(key)
                if "rockfish" in name:
                    reference_detections["rockfish_group"].add(key)
    if total < min_rows or not central_band:
        raise ValueError("OPC DataONE ROV fish-count source is incomplete")
    if any(row_count not in (113, 128) for row_count in units.values()):
        raise ValueError("OPC DataONE sample grouping changed; review source units")
    if any(lat > 2 or lon > 2 for lat, lon in coord_precision):
        raise ValueError("OPC DataONE coordinates now have finer precision; spatial review required")
    if not fractional_positive:
        raise ValueError("OPC DataONE positive-count semantics changed")
    by_site = Counter((key[3], key[5]) for key in units)
    reference_sites = sorted({site for site, designation in by_site if designation == "Reference"})
    return {
        "schema_version": 1,
        "scope": "central-opc-dataone-rov-fish-count-300ft-spot-precision",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "package_url": PACKAGE,
        "object_url": OBJECT,
        "object_sha256": digest.hexdigest(),
        "source_license": "CC BY 4.0 (package metadata)",
        "all_region_rows": total,
        "all_region_zero_count_rows": zeros,
        "central_rows_with_missing_depth": missing_depth,
        "central_rows_200_300ft": central_band,
        "central_location_date_depth_habitat_units_200_300ft": len(units),
        "central_observation_years_by_unit_200_300ft": dict(sorted(unit_years.items())),
        "central_site_designation_units_200_300ft": [
            {"mpa_group": site, "designation": designation, "units": count}
            for (site, designation), count in sorted(by_site.items())
        ],
        "open_reference_detection_units_200_300ft": [
            {"mpa_group": site, "sampled_units": by_site[(site, "Reference")],
             "lingcod_positive_units": sum(key[3] == site for key in reference_detections["lingcod"]),
             "rockfish_group_positive_units": sum(key[3] == site for key in reference_detections["rockfish_group"])}
            for site in reference_sites
        ],
        "coordinate_decimal_places_in_band": [
            {"lat": lat, "lon": lon, "rows": count}
            for (lat, lon), count in sorted(coord_precision.items())
        ],
        "fractional_positive_count_rows_in_band": fractional_positive,
        "independence_from_prior_rov_release_verified": False,
        "native_spot_position_and_swath_verified": False,
        "independent_new_fish_survey": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": "The public table provides historical species/count, habitat, depth and protected/reference context, but coordinates are at most two decimal places (about kilometer scale) and rows repeat a location/depth/habitat unit across species. Some positive counts are fractional, so Count cannot be assumed to be raw individual detections. It lacks original one-second bottom fixes, per-row swath/effort and positional error. Its underlying records may overlap earlier analyzed ROV releases; independence has not been verified, so it is not counted as a second fish survey. It cannot identify an exact fishing spot or resolve chart datum, current access or catch probability.",
    }


def stable(report):
    return {k: v for k, v in report.items() if k != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    report = build(args.input)
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("OPC DataONE ROV source changed; review before promotion")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['central_location_date_depth_habitat_units_200_300ft']} Central depth-band units; no spot-scale coordinates")


if __name__ == "__main__":
    main()

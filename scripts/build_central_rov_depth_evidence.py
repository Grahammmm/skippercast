#!/usr/bin/env python3
"""Summarize reviewed deep ROV observations without publishing survey coordinates."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SPECIES = {"Lingcod": "Lingcod", "Vermilion_rf": "Vermilion rockfish",
           "Copper_rf": "Copper rockfish", "Canary_rf": "Canary rockfish",
           "Yelloweye_rf": "Yelloweye rockfish", "Brown_rf": "Brown rockfish"}


def source_bytes(path, pin):
    data = path.read_bytes()
    if (len(data) != pin["file_bytes"] or hashlib.md5(data).hexdigest() != pin["file_md5"]
            or hashlib.sha256(data).hexdigest() != pin["file_sha256"]):
        raise ValueError("ROV source changed; review before rebuilding")


def fetch(pin, path):
    with urlopen(pin["api_url"], timeout=30) as response:
        record = json.load(response)
    files = {f["key"]: f for f in record["files"]}
    selected = files.get(pin["file_name"])
    if (record["id"] != pin["record_id"] or record["doi"] != pin["doi"]
            or record["metadata"].get("license", {}).get("id") != "cc-by-4.0"
            or not selected or selected["size"] != pin["file_bytes"]
            or selected["checksum"] != "md5:" + pin["file_md5"]):
        raise ValueError("ROV release, rights or object changed")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(pin["file_url"], timeout=90) as response, path.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
    source_bytes(path, pin)


def build(pin, path, minimum_rows=100000):
    source_bytes(path, pin)
    # Paper defines 10 m subunits and observation depth in metres.
    lo, hi = [feet / 3.280839895 for feet in pin["depth_band_ft"]]
    groups = defaultdict(lambda: {"subunits": 0, "surveyed_area_m2": 0.0,
                                  "hard_mixed_sum": 0.0, "years": set(),
                                  "counts": defaultdict(int)})
    seen = set()
    rows = 0
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        needed = {"SurveyYear", "LongTerm_Region", "MPAGroup", "Protection", "Type",
                  "X10m_ID", "Avg.Depth", "Usable_Area_Fish", "Propn_Hard", "Propn_Mixed"} | set(SPECIES)
        if not needed.issubset(reader.fieldnames):
            raise ValueError("ROV subunit schema changed")
        for row in reader:
            rows += 1
            if row["LongTerm_Region"] != "Central" or row["Protection"] != "0" or row["Type"] != "Reference":
                continue
            depth = float(row["Avg.Depth"])
            if not lo <= depth <= hi:
                continue
            identity = row["X10m_ID"]
            if identity in seen:
                raise ValueError("Duplicate ROV subunit")
            seen.add(identity)
            area = float(row["Usable_Area_Fish"])
            hard, mixed = float(row["Propn_Hard"]), float(row["Propn_Mixed"])
            year = int(row["SurveyYear"])
            if (area <= 0 or not 0 <= hard <= 1 or not 0 <= mixed <= 1
                    or hard + mixed > 1.002 or not pin["observation_years"][0] <= year <= pin["observation_years"][1]):
                raise ValueError("Invalid ROV area, habitat or date")
            item = groups[row["MPAGroup"]]
            item["subunits"] += 1
            item["surveyed_area_m2"] += area
            item["hard_mixed_sum"] += hard + mixed
            item["years"].add(year)
            for column in SPECIES:
                count = int(row[column])
                if count < 0:
                    raise ValueError("Negative ROV fish count")
                item["counts"][column] += count
    if rows < minimum_rows or not groups:
        raise ValueError("ROV deep reference evidence incomplete")
    areas = []
    for name in sorted(groups):
        item = groups[name]
        n = item["subunits"]
        areas.append({"area": name, "site_type": "unprotected_reference_only",
                      "observation_years": sorted(item["years"]),
                      "surveyed_10m_subunits": n,
                      "surveyed_camera_area_m2": round(item["surveyed_area_m2"]),
                      "mean_observed_hard_mixed_fraction": round(item["hard_mixed_sum"] / n, 3),
                      "species": [{"name": label, "observed_count": item["counts"][column]}
                                  for column, label in SPECIES.items()]})
    return {"schema_version": 1, "scope": "central-rov-200-300ft-reference-biological-context",
            "fishing_target": False, "exportable": False,
            "source_doi": pin["doi"], "source_url": pin["source_url"],
            "source_file_sha256": pin["file_sha256"], "source_license": pin["license"],
            "depth_band_ft": pin["depth_band_ft"], "source_rows_checked": rows,
            "interpretation_limit": "Historical visual survey counts in 10 m subunits. Not independent fishing trips, catch rates, present-day fish presence at a waypoint, or proof of lawful access.",
            "areas": areas}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--source", type=Path, default=ROOT / "var/review/rov-zenodo-10929417.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/central-rov-200-300ft-evidence.json")
    args = parser.parse_args()
    pin = json.loads((ROOT / "catalog/central-rov-2024-source.json").read_text())
    if args.fetch:
        fetch(pin, args.source)
    result = build(pin, args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Reviewed {result['source_rows_checked']} ROV subunits; {len(result['areas'])} deep open-reference areas")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build bounded, non-positional biological context from the reviewed CCFRP release.

Only open reference-site records are published. A survey grid is not a fishing
waypoint, and this output must never be joined to exact spot rankings.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
AREAS = ("Point Lobos", "Piedras Blancas", "Point Buchon", "Point Conception")
SPECIES = ("Lingcod", "Blue Rockfish", "Black Rockfish", "Vermilion Rockfish",
           "Canary Rockfish", "Copper Rockfish", "Gopher Rockfish")
BASE = "https://opc.dataone.org/metacat/d1/mn/v2/object/"


def checked_bytes(path, pin):
    body = path.read_bytes()
    if len(body) != pin["bytes"] or hashlib.sha256(body).hexdigest() != pin["sha256"]:
        raise ValueError(f"CCFRP source bytes changed: {path}")
    return body


def fetch_and_check(pin, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, item in pin["files"].items():
        path = cache_dir / f"{name}.csv"
        if not path.exists():
            with urlopen(BASE + item["object_id"], timeout=90) as response, path.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
        checked_bytes(path, item)
    with urlopen(pin["metadata_url"], timeout=30) as response:
        metadata = ET.fromstring(response.read())
    rights = " ".join(metadata.find(".//{*}intellectualRights").itertext())
    methods = " ".join(metadata.find(".//{*}methods").itertext())
    entities = {e.attrib["id"] for e in metadata.findall(".//{*}otherEntity")}
    if ("Creative Commons Attribution 4.0" not in rights
            or "less than 40 meters deep" not in methods
            or not all(f["object_id"].replace("urn:uuid:", "urn-uuid-") in entities
                       for f in pin["files"].values())):
        raise ValueError("CCFRP package terms, protocol or referenced objects changed")
    with urlopen(pin["citation_url"], timeout=30) as response:
        publications = response.read().decode(errors="replace")
    release_years = [int(year) for year in re.findall(r"2007\s*[-–]\s*(20\d\d)", publications)]
    if (not release_years or max(release_years) != pin["coverage_years"][1]
            or pin["package_id"].split(":")[-1] not in publications):
        raise ValueError("CCFRP may have published a new release; review and repin before use")


def as_float(value):
    return None if value in ("", "NA") else float(value)


def build(pin, cache_dir, minimum_rows=300000):
    for name, item in pin["files"].items():
        checked_bytes(cache_dir / f"{name}.csv", item)
    with (cache_dir / "location.csv").open(newline="", encoding="latin1") as source:
        locations = {(r["Area"], r["Grid_Cell_ID"]): r for r in csv.DictReader(source)}
    with (cache_dir / "species.csv").open(newline="", encoding="latin1") as source:
        species_names = {r["Common_Name"] for r in csv.DictReader(source)}
    if not set(SPECIES).issubset(species_names):
        raise ValueError("CCFRP target species mapping changed")

    samples = {}
    counts = defaultdict(lambda: defaultdict(int))
    present = defaultdict(lambda: defaultdict(set))
    row_count = 0
    with (cache_dir / "effort.csv").open(newline="", encoding="latin1") as source:
        reader = csv.DictReader(source)
        expected = {"Area", "MPA_Status", "Date", "Year", "ID_Cell_per_Trip",
                    "Grid_Cell_ID", "Total_Angler_Hours", "Common_Name", "Count",
                    "Start_Depth_m", "End_Depth_m"}
        if not expected.issubset(reader.fieldnames):
            raise ValueError("CCFRP effort schema changed")
        for row in reader:
            row_count += 1
            area = row["Area"]
            if area not in AREAS or row["MPA_Status"] != "REF":
                continue
            location = locations.get((area, row["Grid_Cell_ID"]))
            if not location or location["MPA_Status"] != "REF":
                raise ValueError("CCFRP open-reference site cannot be verified")
            year = int(row["Year"])
            if not pin["coverage_years"][0] <= year <= pin["coverage_years"][1]:
                raise ValueError("CCFRP survey year outside reviewed release")
            count = int(row["Count"])
            hours = as_float(row["Total_Angler_Hours"])
            if count < 0 or hours is None or hours <= 0:
                raise ValueError("Invalid CCFRP count or angler effort")
            key = (area, row["Date"], row["ID_Cell_per_Trip"], row["Grid_Cell_ID"])
            depth = [as_float(row[f]) for f in ("Start_Depth_m", "End_Depth_m")]
            depth = max((d for d in depth if d is not None), default=None)
            if key not in samples:
                samples[key] = (hours, depth)
            elif abs(samples[key][0] - hours) > 0.001:
                raise ValueError("Inconsistent CCFRP effort within a sampled grid cell")
            name = row["Common_Name"]
            if name in SPECIES:
                if key in present[area][name]:
                    raise ValueError("Duplicate CCFRP species/cell observation")
                present[area][name].add(key)
                counts[area][name] += count
    if row_count < minimum_rows:
        raise ValueError("CCFRP release unexpectedly incomplete")

    areas = []
    for area in AREAS:
        scoped = {key: value for key, value in samples.items() if key[0] == area}
        if not scoped:
            raise ValueError(f"Missing CCFRP reference effort: {area}")
        hours = sum(v[0] for v in scoped.values())
        if any(len(present[area][name]) != len(scoped) for name in SPECIES):
            raise ValueError(f"CCFRP zero-catch rows missing in {area}")
        years = sorted({int(k[1][:4]) for k in scoped})
        depths = [v[1] for v in scoped.values() if v[1] is not None]
        areas.append({
            "area": area,
            "site_type": "fished_reference_only",
            "evidence_scope": "sparse_single_year" if len(scoped) < 30 or len(years) < 3
                              else "historical_multi_year",
            "sampled_cell_trips": len(scoped),
            "sampled_dates": len({k[1] for k in scoped}),
            "observed_years": [years[0], years[-1]],
            "angler_hours": round(hours, 1),
            "maximum_recorded_sample_depth_m": round(max(depths), 1) if depths else None,
            "species": [{"name": name, "observed_catch": counts[area][name],
                         "catch_per_angler_hour": round(counts[area][name] / hours, 3)}
                        for name in SPECIES],
        })
    return {
        "schema_version": 1,
        "scope": "ccfrp-historical-open-reference-area-context",
        "fishing_target": False,
        "exportable": False,
        "source_package_id": pin["package_id"],
        "source_url": pin["citation_url"],
        "source_license": pin["license"],
        "source_file_sha256": {k: v["sha256"] for k, v in pin["files"].items()},
        "sampling_note": "Standardized hook-and-line rocky-reef grid-cell observations with zero-catch records and angler effort; protected sites excluded. Protocol selects grid cells in water under 40 m, though individual records may be deeper.",
        "interpretation_limit": "Historical area-level context only; no exact location, 200-300 ft validation, present bite prediction, or legal-access conclusion.",
        "source_rows_checked": row_count,
        "areas": areas,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="Fetch and validate official DataONE objects and metadata")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "var/review/ccfrp-2024")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/central-ccfrp-area-evidence.json")
    args = parser.parse_args()
    pin = json.loads((ROOT / "catalog/ccfrp-2024-source.json").read_text())
    if args.fetch:
        fetch_and_check(pin, args.cache_dir)
    result = build(pin, args.cache_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Reviewed {result['source_rows_checked']} CCFRP rows; {len(result['areas'])} open-reference areas")


if __name__ == "__main__":
    main()

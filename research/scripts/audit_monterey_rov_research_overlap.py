#!/usr/bin/env python3
"""Join historical open-reference ROV subunits to Monterey research outlines.

Published output omits coordinates and subunit IDs. A centroid in an outline is
not proof that its imaged bottom footprint or a fish is precisely on a cell.
"""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.ops import transform
from pyproj import Transformer

from research.lib.paths import ROOT

from research.scripts.build_central_rov_depth_evidence import fetch, source_bytes


CONTEXT = ROOT / "dist/data/usgs-offshore-monterey-hard-context.geojson"
MATRIX = ROOT / "research/receipts/monterey-original-300-paired-review.json"
PIN = ROOT / "catalog/central-rov-2024-source.json"
ROCKFISH = ("Copper_rf", "Gopher_rf", "Vermilion_rf", "Canary_rf",
            "Quillback_rf", "Yelloweye_rf", "Brown_rf")
MARGINS = (0, 10, 25)
LOWER_M, UPPER_M = 60.96, 91.44


def build(source: Path, context_path: Path = CONTEXT, pin_path: Path = PIN,
          matrix_path: Path = MATRIX) -> dict:
    pin = json.loads(pin_path.read_text())
    source_bytes(source, pin)
    context = json.loads(context_path.read_text())
    matrix = json.loads(matrix_path.read_text())
    candidate_ids = {row["context_id"] for row in matrix["outlines"]}
    if len(candidate_ids) != 17 or matrix.get("fishing_target") is not False:
        raise ValueError("Original Monterey research matrix changed")
    if context.get("type") != "FeatureCollection":
        raise ValueError("Monterey research geometry changed")
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
    outlines = {}
    for feature in context["features"]:
        ident = feature["properties"].get("id", "")
        if ident in candidate_ids:
            if feature["properties"].get("fishing_target") is not False:
                raise ValueError("Research-only outline changed")
            outlines[ident[-3:]] = transform(project.transform, shape(feature["geometry"]))
    if set(outlines) != {ident[-3:] for ident in candidate_ids}:
        raise ValueError("Original Monterey research outlines changed")
    counts = {ident: {margin: Counter() for margin in MARGINS} for ident in outlines}
    transects = {ident: {margin: set() for margin in MARGINS} for ident in outlines}
    years = {ident: {margin: set() for margin in MARGINS} for ident in outlines}
    survey_groups = {ident: {margin: set() for margin in MARGINS} for ident in outlines}
    nearest = {ident: float("inf") for ident in outlines}
    source_rows = 0
    reference_rows = 0
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"SurveyYear", "LongTerm_Region", "MPAGroup", "Protection",
                    "Type", "X10m_ID", "Avg.X", "Avg.Y", "Avg.Depth",
                    "Usable_Area_Fish", "Propn_Hard", "Propn_Mixed", "Lingcod"} | set(ROCKFISH)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("ROV observation schema changed")
        seen = set()
        for row in reader:
            source_rows += 1
            if (row["LongTerm_Region"] != "Central" or row["Protection"] != "0"
                    or row["Type"] != "Reference"):
                continue
            reference_rows += 1
            ident = row["X10m_ID"]
            if ident in seen or "_" not in ident:
                raise ValueError("Duplicate or ungrouped ROV 10 m subunit")
            seen.add(ident)
            x, y = 1000 * float(row["Avg.X"]), 1000 * float(row["Avg.Y"])
            depth = float(row["Avg.Depth"])
            hard, mixed = float(row["Propn_Hard"]), float(row["Propn_Mixed"])
            area = float(row["Usable_Area_Fish"])
            year = int(row["SurveyYear"])
            if (not -5_000_000 < x < 5_000_000 or not 0 < y < 6_000_000
                    or not 0 <= hard <= 1 or not 0 <= mixed <= 1
                    or hard + mixed > 1.002 or area <= 0
                    or not 2005 <= year <= 2021):
                raise ValueError("ROV coordinates, area, habitat or year invalid")
            point = Point(x, y)
            for outline_id, polygon in outlines.items():
                distance = point.distance(polygon)
                nearest[outline_id] = min(nearest[outline_id], distance)
                if not polygon.contains(point):
                    continue
                if not LOWER_M <= depth <= UPPER_M:
                    continue
                boundary_distance = point.distance(polygon.boundary)
                for margin in MARGINS:
                    if boundary_distance < margin:
                        continue
                    item = counts[outline_id][margin]
                    item["subunits"] += 1
                    item["in_200_300ft_source_depth"] += 1
                    item["majority_observed_hard"] += hard >= 0.5
                    item["lingcod_positive_subunits"] += float(row["Lingcod"]) > 0
                    item["rockfish_positive_subunits"] += any(float(row[name]) > 0 for name in ROCKFISH)
                    item["usable_camera_area_m2"] += area
                    transects[outline_id][margin].add(ident.rsplit("_", 1)[0])
                    years[outline_id][margin].add(year)
                    survey_groups[outline_id][margin].add(row["MPAGroup"])
    if source_rows != 133506 or reference_rows < 10000:
        raise ValueError("ROV source coverage changed")
    results = {}
    for outline_id in sorted(outlines):
        results[outline_id] = {
            "nearest_open_reference_subunit_centroid_m": round(nearest[outline_id], 1),
            "interior_sensitivity": {
                str(margin): {
                    **{key: (round(counts[outline_id][margin][key], 1) if key == "usable_camera_area_m2"
                             else counts[outline_id][margin][key])
                       for key in ("subunits", "in_200_300ft_source_depth", "majority_observed_hard",
                                   "lingcod_positive_subunits", "rockfish_positive_subunits",
                                   "usable_camera_area_m2")},
                    "distinct_transect_labels": len(transects[outline_id][margin]),
                    "observation_years": sorted(years[outline_id][margin]),
                    "source_survey_groups": sorted(survey_groups[outline_id][margin]),
                } for margin in MARGINS
            },
            "source_position_error_bounded": False,
            "mllw_depth_qualified": False,
            "fishing_target": False,
            "exportable": False,
        }
    return {
        "schema_version": 1,
        "scope": "monterey-zenodo-rov-to-original-research-outline-overlap",
        "source_doi": pin["doi"],
        "source_url": pin["source_url"],
        "source_file_sha256": pin["file_sha256"],
        "context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "research_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "source_rows_checked": source_rows,
        "central_open_reference_rows_checked": reference_rows,
        "source_coordinate_interpretation": "Published analysis code treats Avg.X/Avg.Y as UTM zone 10 GRS80 kilometers; source positional error and bottom-camera offset are not bounded here.",
        "position_method_source_url": "https://mareresearch.org/?p=1798",
        "position_method_limit": "MARE describes USBL/ship GPS positioning for its program, but this is not a measured achieved error bound for these historical subunits.",
        "depth_interpretation": "ROV-observed metres, not MLLW-qualified chart depth",
        "outlines": results,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "The 10 m subunits and transects are correlated, not independent trips or catch rates.",
            "This is the same underlying CDFW/MARE ROV program as other processed releases; do not double count it as independent survey evidence.",
            "A 25 m inset is a sensitivity check, not a measured ROV location-error bound.",
            "Historical fish observations do not establish present-day fish presence, a precise pile, legal access or a safe route.",
            "Original subunit coordinates and fishing waypoints are intentionally absent from this research receipt.",
            "Outline 072 has no source-depth ROV centroid remaining after a 25 m inset; it needs original position-error records before candidate-scale use.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--source", type=Path, default=ROOT / "var/review/rov-zenodo-10929417.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "research/receipts/monterey-rov-research-overlap.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    pin = json.loads(PIN.read_text())
    if args.fetch:
        fetch(pin, args.source)
    result = build(args.source)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("ROV research overlap changed; review before any rank")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Joined historical ROV subunits to 17 Monterey research outlines; zero fishing targets")


if __name__ == "__main__":
    main()

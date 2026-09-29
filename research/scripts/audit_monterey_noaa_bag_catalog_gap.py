#!/usr/bin/env python3
"""Check NOAA's NOS BAG catalog over all 17 Monterey 300 ft research outlines.

A missing BAG catalog lead does not prove that no hydrographic survey exists.
This is source acquisition triage, never a fishing target determination.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from shapely.geometry import shape

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repository root, for research.*
from scripts.discover_noaa_surveys import scan
from research.lib.receipts import locate


ROOT = Path(__file__).resolve().parents[2]
MATRIX = "dist/data/monterey-300-source-evidence-matrix.json"
CONTEXT = "dist/data/usgs-offshore-monterey-hard-context.geojson"


def build(matrix, context, scan_fn=scan):
    order = matrix.get("review_order", [])
    if matrix.get("scope") != "monterey-300-source-evidence-review-matrix" or len(order) != 17:
        raise ValueError("Reviewed Monterey research set changed")
    ids = [item["context_id"] for item in order]
    if len(set(ids)) != 17 or context.get("scope") != "generalized-statewide-usgs-hard-bottom-context":
        raise ValueError("Monterey context identity changed")
    features = {f["properties"]["id"]: f for f in context.get("features", [])}
    if any(ident not in features for ident in ids):
        raise ValueError("Monterey reviewed outline geometry missing")
    sectors = []
    for ident in ids:
        geom = shape(features[ident]["geometry"])
        if geom.is_empty or not geom.is_valid:
            raise ValueError("Invalid Monterey research outline")
        west, south, east, north = geom.bounds
        sectors.append({"id": ident,
                        "bounds": [west - .002, south - .002, east + .002, north + .002]})
    result = scan_fn(sectors)
    if (result.get("health", {}).get("status") != "ok"
            or len(result.get("sectors", [])) != 17
            or {r["sector_id"] for r in result["sectors"]} != set(ids)):
        raise ValueError("NOAA NOS BAG catalog scan incomplete")
    rows = []
    for row in result["sectors"]:
        if row.get("status") != "ok" or not row.get("raw_sha256"):
            raise ValueError("NOAA NOS BAG catalog response not fresh")
        bag_ids = sorted(s["id"] for s in row["surveys"])
        rows.append({"context_id": row["sector_id"], "bag_survey_ids": bag_ids,
                     "response_sha256": row["raw_sha256"]})
    rows.sort(key=lambda r: ids.index(r["context_id"]))
    if any(row["bag_survey_ids"] for row in rows):
        raise ValueError("A NOAA BAG lead appeared over a Monterey outline; inspect before changing acquisition priority")
    camera_ids = {x["context_id"] for x in order if x.get("historical_rockfish_positive_windows", 0) > 0}
    return {"schema_version": 1,
            "scope": "monterey-17-research-outlines-noaa-nos-bag-catalog-gap",
            "source_catalog": result["source_url"],
            "research_outline_count": len(ids),
            "historical_rockfish_positive_outline_count": len(camera_ids),
            "buffer_degrees_for_catalog_discovery": .002,
            "outlines_with_downloadable_bag_catalog_leads": 0,
            "catalog_rows": rows,
            "original_measured_mllw_cells_verified_on_outlines": False,
            "depth_uncertainty_gate_satisfied": False,
            "fishing_target": False, "exportable": False,
            "limitations": "NOAA's dynamic NOS survey footprint layer, filtered to BAG downloads, returned no leads over these 17 buffered context outlines. The result is not an exhaustive NOAA or non-NOAA survey inventory, a source-cell join, or proof of no bathymetry. USGS NAVD88 raster cells remain research-only without a validated MLLW transform and full source uncertainty."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("research/receipts/monterey-17-noaa-bag-catalog-gap.json"))
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    inputs = {name: json.loads(locate(path, root).read_text()) for name, path in
              (("matrix", MATRIX), ("context", CONTEXT))}
    report = build(inputs["matrix"], inputs["context"])
    report["source_sha256"] = {name: hashlib.sha256(locate(path, root).read_bytes()).hexdigest()
                               for name, path in (("matrix", MATRIX), ("context", CONTEXT))}
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if report != {key: value for key, value in saved.items() if key != "checked_at"}:
            raise ValueError("NOAA Monterey BAG catalog gap changed; review source")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("17 NOAA BAG catalog outline queries; zero downloadable BAG leads")


if __name__ == "__main__":
    main()

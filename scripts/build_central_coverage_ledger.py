#!/usr/bin/env python3
"""Build an honest Central Coast coverage/gap ledger from published packages.

Package envelopes are browsing extents, never surveyed footprints or fishing
areas. This script does not create or promote a fishing coordinate.
"""

import argparse
import json
import math
from pathlib import Path


REGIONS = (
    "santa-cruz-monterey-bay",
    "monterey-point-sur",
    "big-sur-coast",
    "south-big-sur-san-simeon",
    "cambria-san-simeon",
    "morro-bay",
    "point-arguello-conception",
)
CRITICAL = ("bathymetry", "substrate", "groundtruth", "protected-areas")
SOURCE_LEADS = {
    "santa-cruz-monterey-bay": ("USGS DS 781 Aptos and Monterey Bay original bathymetry/character pairs", "NOAA NOS original BAGs"),
    "monterey-point-sur": ("USGS Offshore Monterey original grids and video", "NOAA NOS original BAGs"),
    "big-sur-coast": ("USGS DS 781 Big Sur blocks and camera observations", "NOAA NOS original BAGs"),
    "south-big-sur-san-simeon": ("USGS DS 781 southern Big Sur blocks", "NOAA NOS original BAGs"),
    "cambria-san-simeon": ("USGS original bathymetry/character survey pairs", "NOAA NOS original BAGs"),
    "morro-bay": ("USGS original surveys beyond the 200 ft source screen", "NOAA NOS original BAGs"),
    "point-arguello-conception": ("NOAA H11952/H11953 original BAGs plus USGS character", "Additional original NOS hydrographic survey footprints"),
}


def read(path):
    return json.loads(Path(path).read_text())


def build(root):
    root = Path(root)
    existing = read(root / "dist/data/atlas.json")
    nbs = read(root / "dist/data/nbs-central-300-depth-screen.json")
    hard = read(root / "dist/data/point-conception-native-hard-300-review-summary.json")
    closure = read(root / "dist/data/central-atlas-300-current-closure-screen.json")
    if nbs["screened_unique_tiles"] != nbs["requested_unique_tiles"] or nbs["failed_tiles"]:
        raise ValueError("Central NBS audit incomplete; coverage ledger cannot be published")
    if not closure["all_geometry_clear_of_screen_buffers"]:
        raise ValueError("Current atlas closure screen failed")
    rows = []
    for region_id in REGIONS:
        package = root / "dist/regions" / region_id
        region = read(root / "regions" / region_id / "region.json")
        coverage = read(package / "coverage.json")
        atlas_path = package / "atlas.json"
        atlas = existing if region_id == "morro-bay" else read(atlas_path)
        research_path = package / "survey-habitat.geojson"
        research_count = len(read(research_path)["features"]) if research_path.exists() else 0
        targets = atlas.get("targets", [])
        if coverage["region_id"] != region_id or coverage["published_targets"] != len(targets):
            raise ValueError(f"Package target count mismatch: {region_id}")
        shallow, deeper = 0, 0
        for target in targets:
            neighborhood = target.get("neighborhood_depth_ft")
            if not isinstance(neighborhood, list) or len(neighborhood) != 2 or not all(
                isinstance(value, (int, float)) and math.isfinite(value) for value in neighborhood
            ):
                raise ValueError(f"Target lacks complete depth patch: {region_id}/{target.get('id')}")
            upper = neighborhood[1]
            if upper <= 200:
                shallow += 1
            elif upper <= 300 and atlas.get("fishing_depth_limit_ft", 0) >= 300 and target.get(
                "depth_qualification", {}
            ).get("status") == "reviewed":
                deeper += 1
            else:
                raise ValueError(f"Unreviewed >200 ft target: {region_id}/{target.get('id')}")
        needs = {n["id"]: n["status"] for n in coverage["needs"] if n["id"] in CRITICAL}
        row = {
            "region_id": region_id,
            "name": region["name"],
            "browsing_bounds_wgs84": region["bounds"],
            "bounds_meaning": "Regional browsing envelope, not a survey footprint, MPA boundary, or fishing area",
            "qualified_targets_at_or_under_200ft": shallow,
            "qualified_targets_200_to_300ft": deeper,
            "research_only_habitat_outlines": research_count,
            "bottom_evidence_status": needs,
            "fishing_coordinate_status": "qualified-reviewed" if targets else "none-qualified",
            "next_source_leads": SOURCE_LEADS[region_id],
            "remaining_gates": [
                "Original measured depth at candidate cell and surrounding drift patch",
                "Reviewed MLLW-equivalent vertical transform and supplied uncertainty",
                "Paired high-resolution substrate plus dated independent groundtruth",
                "Fresh MPA/federal/security and chart-danger screen of full geometry",
                "Current species, season, method and harbor/approach checks",
            ] if not targets else (["No newly qualified 200–300 ft source footprint"] if not deeper else []) + [
                "Independent fish-presence/catch-effort evidence remains absent",
            ],
        }
        rows.append(row)
    if rows[5]["qualified_targets_at_or_under_200ft"] + rows[5]["qualified_targets_200_to_300ft"] != len(existing["targets"]):
        raise ValueError("Morro Bay target count differs from its published atlas")
    return {
        "schema_version": 1,
        "scope": "Monterey Bay to Point Conception regional browsing packages",
        "source_audits": {
            "nbs_300ft": "data/nbs-central-300-depth-screen.json",
            "point_conception_300ft": "data/point-conception-native-hard-300-review-summary.json",
            "existing_target_closures": "data/central-atlas-300-current-closure-screen.json",
        },
        "source_audit_times": {"nbs": nbs["reviewed_at"], "closures": closure["audited_at"], "original_noaa": hard["generated_at"]},
        "depth_planning_ceiling_ft": 300,
        "qualification_ceiling_of_published_targets_ft": 300 if any(r["qualified_targets_200_to_300ft"] for r in rows) else 200,
        "totals": {
            "qualified_targets_at_or_under_200ft": sum(r["qualified_targets_at_or_under_200ft"] for r in rows),
            "qualified_targets_200_to_300ft": sum(r["qualified_targets_200_to_300ft"] for r in rows),
            "research_only_outlines": sum(r["research_only_habitat_outlines"] for r in rows),
            "regions_without_qualified_targets": sum(not r["qualified_targets_at_or_under_200ft"] for r in rows),
        },
        "regions": rows,
        "warning": "Browsing extents do not measure seabed survey coverage. Research outlines are not fishing coordinates. " +
                   ("Zero new >200 ft targets have passed all source and legal gates." if not any(r["qualified_targets_200_to_300ft"] for r in rows)
                    else "Any >200 ft targets require individual depth-qualification receipts and current legal/chart checks."),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dist/data/central-coverage-ledger-v1.json")
    args = parser.parse_args()
    ledger = build(args.root)
    path = Path(args.root) / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2) + "\n")
    print(json.dumps(ledger["totals"], sort_keys=True))


if __name__ == "__main__":
    main()

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
    "point-arguello-conception": ("NOAA H11952/H11953 original 4 m and 8 m MLLW BAG depth cells", "Cellwise uncertainty, independent substrate and full access review before target promotion"),
}


def read(path):
    return json.loads(Path(path).read_text())


def build(root):
    root = Path(root)
    existing = read(root / "dist/data/atlas.json")
    nbs = read(root / "dist/data/nbs-central-300-depth-screen.json")
    hard = read(root / "dist/data/point-conception-native-hard-300-review-summary.json")
    conception_deep_gap = read(root / "dist/data/point-conception-original-bag-200-300ft-gap.json")
    conception_ladder = read(root / "dist/data/point-conception-original-bag-depth-ladder.json")
    conception_rugged = read(root / "dist/data/point-conception-original-4m-rugged-overlap.json")
    conception_8m = read(root / "dist/data/point-conception-original-8m-hard-overlap.json")
    conception_access = read(root / "dist/data/point-conception-original-4m-access-screen.json")
    closure = read(root / "dist/data/central-atlas-300-current-closure-screen.json")
    if nbs["screened_unique_tiles"] != nbs["requested_unique_tiles"] or nbs["failed_tiles"]:
        raise ValueError("Central NBS audit incomplete; coverage ledger cannot be published")
    if not closure["all_geometry_clear_of_screen_buffers"]:
        raise ValueError("Current atlas closure screen failed")
    if (conception_deep_gap.get("scope") != "point-conception-two-original-noaa-bags-200-300ft-exact-file-gap"
            or {row.get("survey_id") for row in conception_deep_gap.get("sources", [])} != {"H11952", "H11953"}
            or conception_deep_gap.get("combined_200_to_300ft_cells") != 0
            or any(row.get("deeper_than_200ft_cells") != 0 for row in conception_deep_gap["sources"])):
        raise ValueError("Point Conception exact-file deep-band gap changed")
    if (conception_ladder.get("scope") != "point-conception-h11952-h11953-eight-original-mllw-bag-depth-tiers"
            or len(conception_ladder.get("sources", [])) != 8
            or conception_ladder.get("nominal_200_to_300ft_cells") != 3990509
            or conception_ladder.get("nominal_200_to_300ft_4m_cells") != 3318707
            or conception_ladder.get("fishing_target") is not False):
        raise ValueError("Point Conception original deep BAG ladder changed")
    if (conception_rugged.get("scope") != "point-conception-original-4m-mllw-usgs-class3-aggregate-overlap"
            or conception_rugged.get("total_inset_components_at_least_2500m2") != 2
            or conception_rugged.get("fishing_target") is not False):
        raise ValueError("Point Conception 4 m rugged overlap changed")
    if (conception_8m.get("scope") != "point-conception-original-8m-mllw-usgs-class2-class3-aggregate-overlap"
            or sum(row["class3_hard_rugged_two_cell_inset"]["inset_components_at_least_2500m2"]
                   for row in conception_8m.get("rows", [])) != 0
            or sum(row["class2_hard_flat_two_cell_inset"]["retained_components_intersecting_requested_region"]
                   for row in conception_8m.get("rows", [])) != 0
            or conception_8m.get("fishing_target") is not False):
        raise ValueError("Point Conception 8 m regional overlap changed")
    if (conception_access.get("scope") != "point-conception-two-original-4m-components-current-gis-screen"
            or len(conception_access.get("components", [])) != 2
            or conception_access.get("fishing_target") is not False):
        raise ValueError("Point Conception 4 m point-in-time access screen changed")
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
            "original_200_300ft_gap": ({
                "receipt": "dist/data/point-conception-original-bag-200-300ft-gap.json",
                "exact_bag_survey_ids": ["H11952", "H11953"],
                "populated_depth_band_cells": 0,
                "scope": "these two BAG files only, not complete surveys or adjacent coast",
            } if region_id == "point-arguello-conception" else None),
            "original_200_300ft_native_lead": ({
                "receipt": "dist/data/point-conception-original-bag-depth-ladder.json",
                "nominal_native_depth_cells": conception_ladder["nominal_200_to_300ft_cells"],
                "nominal_4m_depth_cells": conception_ladder["nominal_200_to_300ft_4m_cells"],
                "status": "research-only; no ranked or exportable deeper targets",
            } if region_id == "point-arguello-conception" else None),
            "original_4m_rugged_overlap": ({
                "receipt": "dist/data/point-conception-original-4m-rugged-overlap.json",
                "inset_components_at_least_2500m2": 2,
                "status": "research-only; source registration and independence unverified",
            } if region_id == "point-arguello-conception" else None),
            "original_8m_hard_overlap": ({
                "receipt": "dist/data/point-conception-original-8m-hard-overlap.json",
                "retained_rugged_patches_at_least_2500m2": 0,
                "retained_hard_flat_patches_inside_requested_region": 0,
                "status": "research-only; 8 m class cannot resolve narrow reef",
            } if region_id == "point-arguello-conception" else None),
            "original_4m_point_in_time_access": ({
                "receipt": "dist/data/point-conception-original-4m-access-screen.json",
                "mapped_gis_held_components_at_review": conception_access["components_held_by_mapped_gis"],
                "reviewed_at": conception_access["source_checked_at"],
                "status": "dated research screen only; recheck before any promotion",
            } if region_id == "point-arguello-conception" else None),
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
            "point_conception_two_bag_deep_gap": "data/point-conception-original-bag-200-300ft-gap.json",
            "point_conception_eight_bag_depth_ladder": "data/point-conception-original-bag-depth-ladder.json",
            "point_conception_4m_rugged_overlap": "data/point-conception-original-4m-rugged-overlap.json",
            "point_conception_8m_hard_overlap": "data/point-conception-original-8m-hard-overlap.json",
            "point_conception_4m_point_in_time_access": "data/point-conception-original-4m-access-screen.json",
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

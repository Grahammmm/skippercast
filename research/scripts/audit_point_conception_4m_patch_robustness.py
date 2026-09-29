#!/usr/bin/env python3
"""Stress-test the two original 4 m Point Conception research patches.

The audit reports aggregate native-cell depth/uncertainty bounds and class
boundary sensitivity, never coordinates or fishable marks.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy.ndimage import binary_erosion, label

from research.lib.paths import ROOT

from research.scripts.audit_point_conception_original_300_gap import CACHE, file_sha256
from research.scripts.audit_point_conception_original_300_ladder import SOURCE_HASHES
from research.scripts.audit_point_conception_4m_hard_overlap import (
    USGS_CACHE, USGS_SOURCE, source_tif,
)


OUTPUT = ROOT / "dist/data/point-conception-original-4m-patch-robustness.json"
PRIOR = ROOT / "dist/data/point-conception-original-4m-rugged-overlap.json"


def summarize_component(mask, elevation, uncertainty):
    depth = -elevation[mask]
    error = uncertainty[mask]
    if not len(depth) or not np.all(np.isfinite(depth)) or not np.all(np.isfinite(error)):
        raise ValueError("Invalid component depth or uncertainty")
    return {
        "native_cells": int(mask.sum()),
        "area_m2": int(mask.sum() * 16),
        "minimum_mllw_depth_m": round(float(depth.min()), 3),
        "maximum_mllw_depth_m": round(float(depth.max()), 3),
        "maximum_supplied_product_uncertainty_m": round(float(error.max()), 3),
        "minimum_depth_minus_supplied_uncertainty_m": round(float((depth - error).min()), 3),
        "all_cells_deeper_than_200ft_after_supplied_uncertainty": bool(np.all(depth - error >= 60.96)),
        "maximum_depth_plus_uncertainty_and_2m_allowance_m": round(float((depth + error + 2).max()), 3),
        "minimum_clearance_to_300ft_after_allowance_m": round(float((91.44 - depth - error - 2).min()), 3),
    }


def audit_one(path, expected_sha, character, character_transform, character_crs):
    if file_sha256(path) != expected_sha:
        raise ValueError("Original BAG changed")
    with rasterio.open(path) as bag:
        if bag.count < 2 or tuple(bag.res) != (4.0, 4.0):
            raise ValueError("Expected 4 m BAG")
        elevation, uncertainty = bag.read(1), bag.read(2)
        placed = np.zeros(elevation.shape, dtype="uint8")
        reproject(character, placed, src_transform=character_transform,
                  src_crs=character_crs, src_nodata=0,
                  dst_transform=bag.transform, dst_crs="EPSG:26910", dst_nodata=0,
                  resampling=Resampling.nearest)
    native_depth = (np.isfinite(elevation) & np.isfinite(uncertainty)
                    & (elevation < 0) & (uncertainty > 0) & (uncertainty <= 1)
                    & (-elevation >= 60.96) & (-elevation + uncertainty + 2 <= 91.44))
    rugged = placed % 10 == 3
    sensitivity = {}
    for inset in (0, 1, 2, 3, 4):
        covered = rugged if inset == 0 else binary_erosion(rugged, iterations=inset, border_value=0)
        labels, _ = label(native_depth & covered)
        sizes = np.bincount(labels.ravel())[1:]
        sensitivity[str(inset * 4)] = {
            "components_at_least_2500m2": int(np.count_nonzero(sizes * 16 >= 2500)),
            "largest_component_area_m2": int(sizes.max() * 16) if sizes.size else 0,
        }
        if inset == 2:
            retained = np.flatnonzero(sizes * 16 >= 2500) + 1
            patches = [summarize_component(labels == index, elevation, uncertainty)
                       for index in retained]
    return {"survey_id": path.name[:6], "boundary_inset_sensitivity_m": sensitivity,
            "eight_meter_inset_patches": patches}


def build():
    prior = json.loads(PRIOR.read_text())
    if prior.get("total_inset_components_at_least_2500m2") != 2 or prior.get("fishing_target") is not False:
        raise ValueError("Reviewed research baseline changed")
    name, url, sha = USGS_SOURCE
    archive = USGS_CACHE / name
    if file_sha256(archive) != sha:
        raise ValueError("USGS character source changed")
    with rasterio.open(source_tif(archive)) as source:
        read = source.read(1, masked=True)
        character = np.where(np.ma.getmaskarray(read), 0, read.data).astype("uint8")
        rows = [audit_one(CACHE / bag_name, bag_sha, character, source.transform, source.crs)
                for files in SOURCE_HASHES.values() for bag_name, bag_sha in files
                if "_4m_" in bag_name]
    if len(rows) != 2 or sum(len(r["eight_meter_inset_patches"]) for r in rows) != 2:
        raise ValueError("Reviewed 4 m research patch count changed")
    return {
        "schema_version": 1, "scope": "point-conception-original-4m-class3-patch-depth-boundary-sensitivity",
        "source_bag_surveys": ["H11952", "H11953"], "usgs_character_url": url,
        "rows": rows, "fishing_target": False, "exportable": False,
        "limitations": [
            "BAG productUncert is reported as supplied; no confidence interval or horizontal error bound is inferred.",
            "Boundary insets test class sensitivity, not actual registration accuracy or positional uncertainty.",
            "USGS class 3 may share acoustic source lineage with NOAA and is not independent bottom or fish groundtruth.",
            "The 2 m allowance is a planning screen, not a water-level or vessel-draft forecast.",
            "No trip-specific security, full-route, drift or biological qualification is implied.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    report = build()
    if args.verify and report != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception patch bounds changed; hold for review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["rows"], indent=2))


if __name__ == "__main__":
    main()

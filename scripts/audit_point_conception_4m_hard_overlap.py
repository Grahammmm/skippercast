#!/usr/bin/env python3
"""Aggregate original Point Conception 4 m depth and USGS rugged-class overlap.

This emits no coordinates, fishable polygons or chartplotter marks. The USGS
class may share acoustic lineage with NOAA, and its boundary inset is a
sensitivity check, not a measured registration-error bound.
"""

import argparse
import json
from pathlib import Path
import zipfile

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy.ndimage import binary_erosion, label
from pyproj import CRS

from scripts.audit_point_conception_original_300_gap import CACHE, ROOT, fetch, file_sha256
from scripts.audit_point_conception_original_300_ladder import SOURCE_HASHES


OUTPUT = ROOT / "dist/data/point-conception-original-4m-rugged-overlap.json"
USGS_CACHE = ROOT / "var/review/point-conception-original-usgs"
USGS_SOURCE = (
    "SeafloorCharacter_OffshorePointConception.zip",
    "https://cmgds.marine.usgs.gov/data/csmp/OffshorePointConception/data/SeafloorCharacter_OffshorePointConception.zip",
    "c5faa08e5162cf09401fa07976333487626a0e2d8732b4e112255b3a8c5733fb",
)
MINIMUM_PATCH_M2 = 2500


def source_tif(path):
    with zipfile.ZipFile(path) as bundle:
        members = [item.filename for item in bundle.infolist()
                   if item.filename.lower().endswith(".tif")]
    if len(members) != 1:
        raise ValueError("USGS character raster member is ambiguous")
    return f"zip://{path.resolve()}!{members[0]}"


def audit_one(bag_path, bag_sha, character_data, character_transform, character_crs):
    if file_sha256(bag_path) != bag_sha:
        raise ValueError(f"Original BAG changed: {bag_path.name}")
    with rasterio.open(bag_path) as bag:
        if bag.count < 2 or tuple(bag.res) != (4.0, 4.0):
            raise ValueError("Expected original 4 m elevation/uncertainty BAG")
        native_crs = CRS.from_user_input(bag.crs)
        horizontal = native_crs.sub_crs_list[0] if native_crs.is_compound else native_crs
        if horizontal.is_bound:
            horizontal = horizontal.source_crs
        if not native_crs.is_compound or horizontal.to_epsg() != 26910:
            raise ValueError("Unexpected BAG horizontal CRS")
        elevation, uncertainty = bag.read(1), bag.read(2)
        # Native BAG horizontal CRS is NAD83 / UTM 10N; the source raster is
        # WGS84 / UTM 10N. The inset below is not a verified transformation error.
        placed = np.zeros(elevation.shape, dtype="uint8")
        reproject(character_data, placed,
                  src_transform=character_transform, src_crs=character_crs, src_nodata=0,
                  dst_transform=bag.transform, dst_crs="EPSG:26910", dst_nodata=0,
                  resampling=Resampling.nearest)
        native_depth = (np.isfinite(elevation) & np.isfinite(uncertainty)
                        & (elevation < 0) & (uncertainty > 0) & (uncertainty <= 1)
                        & (-elevation >= 60.96) & (-elevation + uncertainty + 2 <= 91.44))
        rugged = placed % 10 == 3
        rugged_inset = binary_erosion(rugged, iterations=2, border_value=0)
        joined = native_depth & rugged_inset
        components, component_count = label(joined)
        sizes = np.bincount(components.ravel())[1:]
        retained = sizes[sizes * 16 >= MINIMUM_PATCH_M2]
        return {
            "survey_id": bag_path.name[:6],
            "bag_file": bag_path.name,
            "bag_sha256": bag_sha,
            "native_resolution_m": 4,
            "depth_uncertainty_screen_cells": int(np.count_nonzero(native_depth)),
            "depth_cells_on_nearest_usgs_class3": int(np.count_nonzero(native_depth & rugged)),
            "depth_cells_on_two_cell_inset_class3": int(np.count_nonzero(joined)),
            "inset_contiguous_components": int(component_count),
            "inset_components_at_least_2500m2": int(retained.size),
            "largest_inset_component_m2": int(sizes.max() * 16) if sizes.size else 0,
            "fishing_target": False,
            "exportable": False,
        }


def build(bag_cache=CACHE, usgs_cache=USGS_CACHE):
    name, url, sha = USGS_SOURCE
    previous = json.loads((ROOT / "dist/data/point-conception-native-hard-300-review-summary.json").read_text())
    if (previous.get("scope") != "native-noaa-usgs-review-summary"
            or {row.get("survey_id") for row in previous.get("surveys", [])} != {"H11952", "H11953"}
            or any(not any(source.get("archive_sha256") == sha
                           and source.get("archive_url") == url
                           for source in row.get("usgs_sources", []))
                   for row in previous["surveys"])):
        raise ValueError("USGS class source is not in the reviewed survey registry")
    archive = usgs_cache / name
    if file_sha256(archive) != sha:
        raise ValueError("Original USGS character archive changed")
    with rasterio.open(source_tif(archive)) as source:
        if source.count != 1 or tuple(source.res) != (2.0, 2.0) or source.crs.to_epsg() != 32610:
            raise ValueError("Unexpected original USGS character raster")
        read = source.read(1, masked=True)
        data = np.where(np.ma.getmaskarray(read), 0, read.data).astype("uint8")
        rows = [audit_one(bag_cache / bag_name, bag_sha, data, source.transform, source.crs)
                for files in SOURCE_HASHES.values() for bag_name, bag_sha in files
                if "_4m_" in bag_name]
    if len(rows) != 2:
        raise ValueError("Expected both 4 m Point Conception survey tiers")
    return {
        "schema_version": 1,
        "scope": "point-conception-original-4m-mllw-usgs-class3-aggregate-overlap",
        "usgs_character_url": url,
        "usgs_character_sha256": sha,
        "class_interpretation": "USGS class 3: hard/rugged; mapped class, not an observed boulder size or independent fish sighting",
        "rows": rows,
        "total_inset_components_at_least_2500m2": sum(row["inset_components_at_least_2500m2"] for row in rows),
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "Rugged-class overlap is a terrain/substrate research lead; acoustic source independence is unverified.",
            "The two-cell (8 m) inset tests boundary sensitivity, not achieved source registration or horizontal uncertainty.",
            "No fresh MPA, security, ENC danger, drift or route clearance is included.",
            "No dated fish observation or effort is spatially linked to these components.",
            "Aggregate counts intentionally omit coordinates, polygons and chartplotter exports.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag-cache", type=Path, default=CACHE)
    parser.add_argument("--usgs-cache", type=Path, default=USGS_CACHE)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch:
        name, url, sha = USGS_SOURCE
        fetch(args.usgs_cache / name, url, sha)
        for survey_id, files in SOURCE_HASHES.items():
            for bag_name, bag_sha in files:
                if "_4m_" in bag_name:
                    bag_url = f"https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/{survey_id}/BAG/{bag_name}"
                    fetch(args.bag_cache / bag_name, bag_url, bag_sha)
    report = build(args.bag_cache, args.usgs_cache)
    if args.verify and report != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception 4 m rugged overlap changed; hold for review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Audited original 4 m depth and USGS class-3 overlap; no fishable spots emitted")


if __name__ == "__main__":
    main()

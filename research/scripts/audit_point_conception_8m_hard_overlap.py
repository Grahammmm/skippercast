#!/usr/bin/env python3
"""Audit original 8 m Point Conception BAG depth versus USGS hard classes.

The paired USGS class may reuse 2008 acoustic source lines. This publishes
aggregate research counts, not target geometry, rock sizes, fishing ranks or
chartplotter marks.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from pyproj import CRS
from pyproj import Transformer
import rasterio
from rasterio.features import shapes
from rasterio.warp import reproject, Resampling
from scipy.ndimage import binary_erosion, label
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union

from research.scripts.audit_point_conception_4m_hard_overlap import USGS_CACHE, USGS_SOURCE, source_tif
from research.lib.paths import ROOT
from research.scripts.audit_point_conception_original_300_gap import CACHE, file_sha256
from research.scripts.audit_point_conception_original_300_ladder import SOURCE_HASHES


OUTPUT = ROOT / "dist/data/point-conception-original-8m-hard-overlap.json"
MIN_COMPONENT_M2 = 2500
REGION = ROOT / "regions/point-arguello-conception/region.json"


def components(mask, *, native_transform, to_geo, fishing_bounds):
    labels, count = label(mask)
    sizes = np.bincount(labels.ravel())[1:] * 64
    kept = sizes[sizes >= MIN_COMPONENT_M2]
    retained_ids = [int(i) for i in np.where(np.bincount(labels.ravel()) * 64 >= MIN_COMPONENT_M2)[0] if i]
    region = box(*fishing_bounds)
    intersects_region = 0
    northmost_lat = None
    for component in retained_ids:
        selected = labels == component
        polygons = [shape(geometry) for geometry, value in shapes(
            selected.astype("uint8"), mask=selected, transform=native_transform) if value]
        footprint = unary_union(polygons)
        if not footprint.is_valid or int(footprint.area) != int(selected.sum() * 64):
            raise ValueError("8 m research component polygon changed")
        geographic = transform(to_geo, footprint)
        intersects_region += int(geographic.intersects(region))
        northmost_lat = max(northmost_lat or -90, geographic.bounds[3])
    return {
        "inset_cells": int(mask.sum()),
        "inset_components": int(count),
        "inset_components_at_least_2500m2": int(len(kept)),
        "largest_inset_component_m2": int(sizes.max()) if len(sizes) else 0,
        "largest_five_retained_component_areas_m2": sorted((int(x) for x in kept), reverse=True)[:5],
        "retained_components_intersecting_requested_region": intersects_region,
        "retained_component_northmost_latitude": round(northmost_lat, 5) if northmost_lat is not None else None,
    }


def cells_in_region(mask, native_transform, to_geo, fishing_bounds):
    rows, columns = np.where(mask)
    if not len(rows):
        return 0
    if native_transform.b or native_transform.d:
        raise ValueError("Rotated original BAG needs explicit cell transformation review")
    x = native_transform.c + (columns + 0.5) * native_transform.a
    y = native_transform.f + (rows + 0.5) * native_transform.e
    lon, lat = to_geo(x, y)
    west, south, east, north = fishing_bounds
    return int(np.count_nonzero((lon >= west) & (lon <= east)
                                    & (lat >= south) & (lat <= north)))


def audit(bag_cache=CACHE, usgs_cache=USGS_CACHE):
    name, url, sha = USGS_SOURCE
    archive = usgs_cache / name
    if file_sha256(archive) != sha:
        raise ValueError("Original USGS character archive changed")
    region = json.loads(REGION.read_text())
    fishing_bounds = region["fishing_bounds"]
    if region["id"] != "point-arguello-conception" or fishing_bounds[1] != 34.45:
        raise ValueError("Point Conception regional southern boundary changed")
    to_geo = Transformer.from_crs(26910, 4326, always_xy=True).transform
    rows = []
    with rasterio.open(source_tif(archive)) as source:
        read = source.read(1, masked=True)
        character = np.where(np.ma.getmaskarray(read), 0, read.data).astype("uint8")
        if source.crs.to_epsg() != 32610 or tuple(source.res) != (2.0, 2.0):
            raise ValueError("Unexpected original USGS character grid")
        for survey, files in SOURCE_HASHES.items():
            bag_name, bag_sha = next(item for item in files if "_8m_" in item[0])
            path = bag_cache / bag_name
            if file_sha256(path) != bag_sha:
                raise ValueError(f"Original BAG changed: {survey}")
            with rasterio.open(path) as bag:
                if tuple(bag.res) != (8.0, 8.0):
                    raise ValueError("Unexpected original 8 m BAG resolution")
                native_crs = CRS.from_user_input(bag.crs)
                horizontal = native_crs.sub_crs_list[0] if native_crs.is_compound else native_crs
                if horizontal.is_bound:
                    horizontal = horizontal.source_crs
                if not native_crs.is_compound or horizontal.to_epsg() != 26910:
                    raise ValueError("Unexpected original BAG horizontal CRS")
                elevation, uncertainty = bag.read(1), bag.read(2)
                placed = np.zeros(elevation.shape, dtype="uint8")
                reproject(character, placed, src_transform=source.transform,
                          src_crs=source.crs, src_nodata=0,
                          dst_transform=bag.transform, dst_crs="EPSG:26910", dst_nodata=0,
                          resampling=Resampling.nearest)
                depth = -elevation
                eligible = (np.isfinite(elevation) & np.isfinite(uncertainty)
                            & (elevation < 0) & (uncertainty > 0) & (uncertainty <= 1)
                            & (depth >= 60.96) & (depth + uncertainty + 2 <= 91.44))
                class2 = placed % 10 == 2
                class3 = placed % 10 == 3
                class2_inset = eligible & binary_erosion(class2, iterations=2, border_value=0)
                class3_inset = eligible & binary_erosion(class3, iterations=2, border_value=0)
                rows.append({
                    "survey_id": survey,
                    "bag_file": bag_name,
                    "bag_sha256": bag_sha,
                    "native_resolution_m": 8,
                    "depth_uncertainty_screen_cells": int(eligible.sum()),
                    "class2_hard_flat_raw_overlap_cells": int((eligible & class2).sum()),
                    "class3_hard_rugged_raw_overlap_cells": int((eligible & class3).sum()),
                    "requested_region_class2_raw_cells": cells_in_region(eligible & class2, bag.transform, to_geo, fishing_bounds),
                    "requested_region_class3_raw_cells": cells_in_region(eligible & class3, bag.transform, to_geo, fishing_bounds),
                    "requested_region_class2_inset_cells": cells_in_region(class2_inset, bag.transform, to_geo, fishing_bounds),
                    "requested_region_class3_inset_cells": cells_in_region(class3_inset, bag.transform, to_geo, fishing_bounds),
                    "class2_hard_flat_two_cell_inset": components(
                        class2_inset,
                        native_transform=bag.transform, to_geo=to_geo, fishing_bounds=fishing_bounds),
                    "class3_hard_rugged_two_cell_inset": components(
                        class3_inset,
                        native_transform=bag.transform, to_geo=to_geo, fishing_bounds=fishing_bounds),
                    "fishing_target": False,
                    "exportable": False,
                })
    if len(rows) != 2:
        raise ValueError("Expected both original 8 m survey tiers")
    return {
        "schema_version": 1,
        "scope": "point-conception-original-8m-mllw-usgs-class2-class3-aggregate-overlap",
        "usgs_character_url": url,
        "usgs_character_sha256": sha,
        "usgs_class2": "Interpreted hard/flat, not photographed bedrock or large boulders",
        "usgs_class3": "Interpreted hard/rugged, not an independently verified fish site",
        "requested_region_id": region["id"],
        "requested_region_southern_latitude": fishing_bounds[1],
        "rows": rows,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "The USGS class may reuse the 2008 Fugro acoustic soundings behind the NOAA BAG; independent acoustic validation is not established.",
            "Nearest-neighbor reprojection from 2 m to 8 m can omit narrow rock bands. A zero retained component is not proof that no rock exists.",
            "The two-cell (16 m) inset is a boundary sensitivity test, not an achieved registration-error bound.",
            "A broad class-2 hard/flat area is not a discrete rock pile or species observation; edges, substrate truth and fish effort remain unverified.",
            "The retained 8 m class-2 areas are outside the requested Point Conception region. Regional survey-file overlap alone cannot promote them into the Central Coast map.",
            "No current full-footprint MPA, security, chart, route or species-rule clearance is included.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag-cache", type=Path, default=CACHE)
    parser.add_argument("--usgs-cache", type=Path, default=USGS_CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    report = audit(args.bag_cache, args.usgs_cache)
    if args.verify and report != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception 8 m substrate overlap changed; hold for review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"surveys": len(report["rows"]),
                      "rugged_retained": sum(x["class3_hard_rugged_two_cell_inset"]["inset_components_at_least_2500m2"] for x in report["rows"]),
                      "flat_retained": sum(x["class2_hard_flat_two_cell_inset"]["inset_components_at_least_2500m2"] for x in report["rows"])}))


if __name__ == "__main__":
    main()

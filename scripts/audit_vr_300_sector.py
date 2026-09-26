#!/usr/bin/env python3
"""Re-screen a pinned original NOAA VR BAG for 200–300 ft source-depth leads.

Counts are assigned by native supergrid center to an approximate browse sector.
They do not identify habitat, a fishing coordinate, a legal area or a safe route.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import h5py
import numpy as np
from pyproj import CRS, Transformer
import rasterio

from scripts.screen_vr_native_depth import fine_grid_rows
from scripts.audit_nbs_modeling_tile import sha256
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, vr_transform


FT_PER_M = 3.280839895013123


def audit(bag, source_review, survey_id, sector):
    rows = [row for row in source_review["files"] if row.get("survey_id") == survey_id
            and row.get("status") == "ok"]
    if len(rows) != 1:
        raise ValueError("Expected one previously reviewed original BAG")
    receipt = rows[0]
    if (source_review.get("status") != "ok" or
            source_review.get("scope") != "california-original-vr-native-depth-review" or
            sha256(bag) != receipt["bag_sha256"]):
        raise ValueError("Original BAG or source review changed")
    if len(sector["bounds"]) != 4:
        raise ValueError("Invalid browse sector")
    counts = {key: 0 for key in ("fine_supergrids", "measured_cells",
                                      "nominal_200_300ft_cells",
                                      "depth_uncertainty_qualified_200_300ft_cells",
                                      "depth_uncertainty_qualified_25_300ft_cells")}
    eligible_centers = []
    with h5py.File(bag) as h, rasterio.open(bag) as raster:
        root = h["BAG_root"]
        original = bag_metadata(root["metadata"][:].tobytes().decode().rstrip("\0"), survey_id)
        if original["metadata_sha256"] != receipt["metadata_sha256"]:
            raise ValueError("Original BAG metadata changed")
        horizontal = CRS.from_wkt(original["horizontal_wkt"])
        if horizontal.is_bound:
            horizontal = horizontal.source_crs
        to_geo = Transformer.from_crs(horizontal, "EPSG:4326", always_xy=True)
        metadata = root["varres_metadata"][:]
        refinements = root["varres_refinements"]
        indices = fine_grid_rows(metadata)
        if len(indices) != receipt["counts"]["fine_native_grids"]:
            raise ValueError("Fine-grid inventory changed")
        for row, col in indices:
            item = metadata[row, col]
            nx, ny = int(item["dimensions_x"]), int(item["dimensions_y"])
            spacing = max(float(item["resolution_x"]), float(item["resolution_y"]))
            transform = vr_transform(raster.bounds.left, raster.bounds.bottom,
                                     raster.res[0], raster.res[1], int(row), int(col), item)
            lon, lat = to_geo.transform(transform.c + nx * float(item["resolution_x"]) / 2,
                                        transform.f - ny * float(item["resolution_y"]) / 2)
            west, south, east, north = sector["bounds"]
            if not (west <= lon < east and south <= lat < north):
                continue
            offset, size = int(item["index"]), nx * ny
            if offset < 0 or offset + size > refinements.shape[1]:
                raise ValueError("BAG refinement index outside source array")
            values = refinements[0, offset:offset + size]
            depth, uncertainty = values["depth"], values["depth_uncrt"]
            measured = (np.isfinite(depth) & np.isfinite(uncertainty) &
                        (depth < 0) & (depth > -3000) &
                        (uncertainty > 0) & (uncertainty < 100))
            band = measured & (depth <= -200 / FT_PER_M) & (depth >= -300 / FT_PER_M)
            qualified = cells_qualified(depth, uncertainty, spacing, limit_ft=300) & measured
            counts["fine_supergrids"] += 1
            counts["measured_cells"] += int(np.count_nonzero(measured))
            counts["nominal_200_300ft_cells"] += int(np.count_nonzero(band))
            counts["depth_uncertainty_qualified_200_300ft_cells"] += int(np.count_nonzero(band & qualified))
            counts["depth_uncertainty_qualified_25_300ft_cells"] += int(np.count_nonzero(qualified))
            if np.any(qualified):
                eligible_centers.append((lon, lat))
    eligible_bounds = ([min(point[0] for point in eligible_centers),
                        min(point[1] for point in eligible_centers),
                        max(point[0] for point in eligible_centers),
                        max(point[1] for point in eligible_centers)] if eligible_centers else None)
    return {"schema_version": 1, "scope": "original-noaa-vr-300ft-browse-sector-screen",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "survey_id": survey_id, "source_url": receipt["bag_url"],
            "source_sha256": receipt["bag_sha256"],
            "source_report_url": receipt["source_report_url"],
            "survey_dates": receipt["survey_dates"], "vertical_datum": "MLLW",
            "sector_id": sector["id"], "sector_bounds": sector["bounds"],
            "counts": counts, "eligible_supergrid_center_bounds": eligible_bounds,
            "fishing_target": False, "exportable": False,
            "limitations": "Fine-grid counts use approximate browse-sector assignment by supergrid center. Depth/uncertainty qualification is only a source screen. No substrate, fish presence, current MPA/GEA/security/ENC clearance, transit or safe drift has been established."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", type=Path, required=True)
    parser.add_argument("--source-review", type=Path, default=Path("dist/data/noaa-vr-native-depth-review.json"))
    parser.add_argument("--sectors", type=Path, default=Path("dist/data/coastal-sectors.json"))
    parser.add_argument("--survey-id", required=True)
    parser.add_argument("--sector-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sectors = [row for row in json.loads(args.sectors.read_text())["sectors"] if row["id"] == args.sector_id]
    if len(sectors) != 1:
        raise ValueError("Unknown browse sector")
    result = audit(args.bag, json.loads(args.source_review.read_text()), args.survey_id, sectors[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["survey_id"], result["sector_id"], result["counts"])


if __name__ == "__main__":
    main()

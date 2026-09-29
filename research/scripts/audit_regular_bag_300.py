#!/usr/bin/env python3
"""Screen an original regular NOAA BAG's measured MLLW pixels to 300 ft.

This is a bounded source review. Depth-qualified cells are not fishing spots:
substrate, full-area closures, access, chart hazards and fish evidence remain
independent release gates.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from pyproj import Transformer

from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, source_url_allowed


def summarize(elevation, uncertainty, resolution_m):
    measured = (np.isfinite(elevation) & (elevation < 0) & (elevation > -3000)
                & np.isfinite(uncertainty) & (uncertainty > 0) & (uncertainty < 100))
    values = -elevation[measured]
    error = uncertainty[measured]
    valid_300 = measured & cells_qualified(elevation, uncertainty, resolution_m, limit_ft=300)
    valid_200 = measured & cells_qualified(elevation, uncertainty, resolution_m, limit_ft=200)
    nominal_band = measured & (-elevation >= 200 * .3048) & (-elevation <= 300 * .3048)
    return {
        "measured_native_cells": int(np.count_nonzero(measured)),
        "minimum_depth_m_below_mllw": round(float(values.min()), 3) if values.size else None,
        "maximum_depth_m_below_mllw": round(float(values.max()), 3) if values.size else None,
        "minimum_product_uncertainty_m": round(float(error.min()), 3) if error.size else None,
        "maximum_product_uncertainty_m": round(float(error.max()), 3) if error.size else None,
        "eligible_25_200ft_cells_with_margin": int(np.count_nonzero(valid_200)),
        "eligible_25_300ft_cells_with_margin": int(np.count_nonzero(valid_300)),
        "nominal_200_300ft_cells": int(np.count_nonzero(nominal_band)),
        "nominal_200_300ft_cells_passing_300ft_uncertainty_margin": int(np.count_nonzero(nominal_band & valid_300)),
    }


def aggregate_grid(grid, sector=None):
    fields = ("measured_native_cells", "eligible_25_200ft_cells_with_margin",
              "eligible_25_300ft_cells_with_margin", "nominal_200_300ft_cells",
              "nominal_200_300ft_cells_passing_300ft_uncertainty_margin")
    total = {key: 0 for key in fields}
    extrema = {"minimum_depth_m_below_mllw": None, "maximum_depth_m_below_mllw": None,
               "minimum_product_uncertainty_m": None, "maximum_product_uncertainty_m": None}
    in_sector = {"eligible_25_300ft_cells_with_margin": 0,
                 "nominal_200_300ft_cells_passing_300ft_uncertainty_margin": 0}
    to_geo = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True) if sector else None
    for _, window in grid.block_windows(1):
        elevation = grid.read(1, window=window)
        uncertainty = grid.read(2, window=window)
        part = summarize(elevation, uncertainty, max(grid.res))
        for key in fields:
            total[key] += part[key]
        for key in ("minimum_depth_m_below_mllw", "minimum_product_uncertainty_m"):
            if part[key] is not None:
                extrema[key] = part[key] if extrema[key] is None else min(extrema[key], part[key])
        for key in ("maximum_depth_m_below_mllw", "maximum_product_uncertainty_m"):
            if part[key] is not None:
                extrema[key] = part[key] if extrema[key] is None else max(extrema[key], part[key])
        if sector:
            eligible = cells_qualified(elevation, uncertainty, max(grid.res), limit_ft=300)
            rows, cols = np.where(eligible)
            if not len(rows):
                continue
            x, y = grid.window_transform(window) * (cols + .5, rows + .5)
            lon, lat = to_geo.transform(x, y)
            west, south, east, north = sector["bounds"]
            inside = (lon >= west) & (lon < east) & (lat >= south) & (lat < north)
            in_sector["eligible_25_300ft_cells_with_margin"] += int(np.count_nonzero(inside))
            band = (-elevation[rows, cols] >= 200 * .3048) & (-elevation[rows, cols] <= 300 * .3048)
            in_sector["nominal_200_300ft_cells_passing_300ft_uncertainty_margin"] += int(np.count_nonzero(inside & band))
    return {**total, **extrema}, in_sector


def audit(path, survey_id, source_url, expected_sha, sector=None):
    if not source_url_allowed(source_url) or f"/{survey_id}/BAG/" not in source_url:
        raise ValueError("BAG URL not bound to the original survey")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha:
        raise ValueError("Original BAG digest changed")
    with h5py.File(path) as bundle, rasterio.open(path) as grid:
        root = bundle["BAG_root"]
        metadata = bag_metadata(root["metadata"][:].tobytes().decode().rstrip("\0"), survey_id)
        if (metadata["vertical_datum"] != "MLLW" or metadata["uncertainty_type"] != "productUncert"
                or grid.count < 2 or max(grid.res) > 4
                or root["elevation"].shape != root["uncertainty"].shape
                or root["elevation"].shape != (grid.height, grid.width)
                or "varres_refinements" in root):
            raise ValueError("Expected original regular MLLW BAG with product uncertainty")
        measured, in_sector = aggregate_grid(grid, sector)
        bounds = transform_bounds(grid.crs, "EPSG:4326", *grid.bounds, densify_pts=21)
        return {"schema_version": 1, "scope": "original-regular-bag-300-depth-source-review",
                "audited_at": datetime.now(timezone.utc).isoformat(),
                "survey_id": survey_id, "source_url": source_url, "file_sha256": digest,
                "metadata_sha256": metadata["metadata_sha256"],
                "survey_start": metadata["survey_start"], "survey_end": metadata["survey_end"],
                "vertical_datum": "MLLW", "uncertainty_type": "productUncert",
                "native_resolution_m": list(grid.res),
                "raster_bounds_wgs84": [round(v, 7) for v in bounds],
                "policy": {"minimum_ft": 25, "ceiling_ft": 300,
                           "planning_margin_m": 2, "maximum_product_uncertainty_m": 1},
                "counts": measured,
                "sector_cell_center_screen": {"sector_id": sector["id"], "bounds_wgs84": sector["bounds"],
                                               "counts": in_sector} if sector else None,
                "fishing_target": False, "exportable": False,
                "limitations": "Measured cell centers, paired original substrate and independent groundtruth, protected-area/security/chart screens and source-age review are required before any candidate geometry. This BAG is not a navigation chart or fish observation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", type=Path, required=True)
    parser.add_argument("--survey-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--sector-id", help="Optional reviewed California browse sector for native cell-center counts")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sector = None
    if args.sector_id:
        sectors = json.loads(Path("dist/data/coastal-sectors.json").read_text())["sectors"]
        sector = next((row for row in sectors if row["id"] == args.sector_id), None)
        if sector is None:
            raise ValueError("Unknown reviewed California browse sector")
    result = audit(args.bag, args.survey_id, args.source_url, args.sha256, sector)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{args.survey_id}: {result['counts']['eligible_25_300ft_cells_with_margin']} eligible native depth cells; zero fishing targets")


if __name__ == "__main__":
    main()

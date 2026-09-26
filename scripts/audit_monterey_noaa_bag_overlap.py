#!/usr/bin/env python3
"""Bounded original NOAA BAG cell overlap with USGS Monterey research outlines.

This tests measured MLLW depth/uncertainty coverage, not habitat or permission.
Eight- and sixteen-meter source grids are retained as research leads only.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import rasterio
from rasterio.mask import mask
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from skippercast.platform.bottom_targets import bag_metadata, source_url_allowed


def count_overlap(grid, geometry):
    projected = transform(Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform, geometry)
    try:
        data, _ = mask(grid, [mapping(projected)], crop=True, filled=False)
    except ValueError as exc:
        if "do not overlap" in str(exc):
            return {"measured_native_cells": 0, "nominal_200_300ft_cells": 0,
                    "nominal_200_300ft_cells_below_300ft_with_product_uncertainty_and_margin": 0}
        raise
    elevation, uncertainty = data[0], data[1]
    valid = (~np.ma.getmaskarray(elevation) & ~np.ma.getmaskarray(uncertainty)
             & np.isfinite(elevation.data) & np.isfinite(uncertainty.data)
             & (elevation.data < 0) & (elevation.data > -3000)
             & (uncertainty.data > 0) & (uncertainty.data < 100))
    band = valid & (-elevation.data >= 200 * .3048) & (-elevation.data <= 300 * .3048)
    depth_allowance = valid & (uncertainty.data <= 1) & (
        -elevation.data + uncertainty.data + 2 <= 300 * .3048)
    return {"measured_native_cells": int(np.count_nonzero(valid)),
            "nominal_200_300ft_cells": int(np.count_nonzero(band)),
            "nominal_200_300ft_cells_below_300ft_with_product_uncertainty_and_margin": int(
                np.count_nonzero(band & depth_allowance))}


def audit(bag, survey_id, source_url, expected_sha, context, pixel):
    if not source_url_allowed(source_url) or f"/{survey_id}/BAG/" not in source_url:
        raise ValueError("BAG URL not bound to the original NOAA survey")
    digest = hashlib.sha256(bag.read_bytes()).hexdigest()
    if digest != expected_sha:
        raise ValueError("Original BAG bytes changed")
    if pixel.get("scope") != "monterey-original-pixel-depth-band-audit" or pixel.get("fishing_target") is not False:
        raise ValueError("Wrong Monterey research receipt")
    features = {f["properties"]["id"]: f for f in context["features"]}
    with h5py.File(bag) as bundle, rasterio.open(bag) as grid:
        root = bundle["BAG_root"]
        metadata = bag_metadata(root["metadata"][:].tobytes().decode().rstrip("\0"), survey_id)
        if (metadata["vertical_datum"] != "MLLW" or metadata["uncertainty_type"] != "productUncert"
                or grid.count < 2 or max(grid.res) > 16
                or root["elevation"].shape != root["uncertainty"].shape
                or root["elevation"].shape != (grid.height, grid.width)
                or "varres_refinements" in root):
            raise ValueError("Expected original regular MLLW BAG and uncertainty")
        rows = []
        for item in pixel["outlines"]:
            feature = features[item["context_id"]]
            if feature["properties"].get("fishing_target") is not False:
                raise ValueError("Research outline promoted unexpectedly")
            rows.append({"context_id": item["context_id"], **count_overlap(grid, shape(feature["geometry"]))})
    return {"schema_version": 1, "scope": "monterey-original-noaa-bag-cell-overlap",
            "audited_at": datetime.now(timezone.utc).isoformat(), "survey_id": survey_id,
            "source_url": source_url, "file_sha256": digest, "metadata_sha256": metadata["metadata_sha256"],
            "survey_start": metadata["survey_start"], "survey_end": metadata["survey_end"],
            "native_resolution_m": list(grid.res), "vertical_datum": "MLLW",
            "four_meter_habitat_resolution_gate_passed": max(grid.res) <= 4,
            "uncertainty_type": "productUncert", "outline_count": len(rows),
            "outlines_with_measured_cells": sum(r["measured_native_cells"] > 0 for r in rows),
            "measured_native_cells_inside_research_outlines": sum(r["measured_native_cells"] for r in rows),
            "nominal_200_300ft_cells_below_cap_with_uncertainty_margin_inside_research_outlines": sum(
                r["nominal_200_300ft_cells_below_300ft_with_product_uncertainty_and_margin"] for r in rows),
            "outlines": rows, "fishing_target": False, "exportable": False,
            "limitations": "Exact native cell overlap of generalized historic USGS research polygons only. No BAG cell has been paired to original rock-class pixels, current legal/chart access, or independent fish evidence. A zero overlap does not refute other parts of the survey or other NOAA surveys."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bag", type=Path, required=True)
    p.add_argument("--survey-id", required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--context", type=Path, default=Path("dist/data/usgs-offshore-monterey-hard-context.geojson"))
    p.add_argument("--pixel", type=Path, default=Path("dist/data/monterey-original-300-pixel-review.json"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = audit(args.bag, args.survey_id, args.source_url, args.sha256,
                   json.loads(args.context.read_text()), json.loads(args.pixel.read_text()))
    result["context_sha256"] = hashlib.sha256(args.context.read_bytes()).hexdigest()
    result["pixel_review_sha256"] = hashlib.sha256(args.pixel.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{args.survey_id}: {result['outlines_with_measured_cells']} outlines with measured BAG cells; zero fishing targets")


if __name__ == "__main__":
    main()

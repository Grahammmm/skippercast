#!/usr/bin/env python3
"""Count native Monterey USGS NAVD88 cells in a 200–300 ft comparison band.

The band is a research filter, not an MLLW depth qualification or a fish spot.
Original archive SHA, outline geometry, native CRS and prior measured-cell
counts must agree before a receipt is written.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import rasterio
from rasterio.mask import mask
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from scripts.build_monterey_300_research_queue import LOWER_M, UPPER_M


def count_band(elevations):
    values = np.ma.asarray(elevations).compressed()
    values = values[np.isfinite(values)]
    depths = -values.astype("float64")
    return len(values), int(np.count_nonzero((depths >= LOWER_M) & (depths <= UPPER_M)))


def audit(archive, prior, queue, context):
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != prior["bathymetry_sha256"] or digest != queue["source_review_sha256"]:
        raise ValueError("Original Monterey USGS archive SHA changed")
    if (queue["scope"] != "monterey-native-200-300ft-research-priority"
            or queue["native_vertical_datum"] != "NAVD88"
            or queue["fishing_target"] is not False
            or prior["vertical_datum"] != "NAVD88"
            or prior["mllw_conversion_reviewed"] is not False
            or prior["product_uncertainty_grid_available"] is not False):
        raise ValueError("Unreviewed depth datum or research promotion state")
    features = {feature["properties"]["id"]: feature for feature in context["features"]}
    prior_rows = {row["context_id"]: row for row in prior["outlines"]}
    with zipfile.ZipFile(archive) as bundle:
        tiffs = [name for name in bundle.namelist() if name.lower().endswith(".tif")]
        if len(tiffs) != 1:
            raise ValueError("Expected one original Monterey GeoTIFF")
    results = []
    with rasterio.open(f"zip://{archive.resolve()}!{tiffs[0]}") as grid:
        if grid.count != 1 or str(grid.crs) != "EPSG:26910" or any(abs(r - 2) > .01 for r in grid.res):
            raise ValueError("Unexpected original Monterey grid CRS or resolution")
        project = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform
        for row in queue["priority_order"]:
            ident = row["context_id"]
            feature = features.get(ident)
            if not feature or ident not in prior_rows:
                raise ValueError(f"Missing original context or prior audit for {ident}")
            geometry = transform(project, shape(feature["geometry"]))
            clipped, _ = mask(grid, [mapping(geometry)], crop=True, filled=False)
            valid, band = count_band(clipped[0])
            if valid != row["native_measured_cells_in_full_outline"] or valid != prior_rows[ident]["native_measured_cells"]:
                raise ValueError(f"Original measured-cell count changed for {ident}")
            results.append({"context_id": ident,
                            "native_valid_cells_in_outline": valid,
                            "native_cells_200_300ft_below_navd88": band,
                            "native_2m_cell_area_in_band_m2": band * 4,
                            "historical_camera_windows": row["historical_camera_windows"],
                            "historical_rockfish_positive_windows": row["historical_rockfish_positive_windows"],
                            "fishing_target": False, "exportable": False})
    return {"schema_version": 1, "scope": "monterey-original-pixel-depth-band-audit",
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "source_archive_url": prior["bathymetry_url"], "source_archive_sha256": digest,
            "native_vertical_datum": "NAVD88", "native_resolution_m": 2,
            "comparison_band_m_below_navd88": [round(LOWER_M, 3), round(UPPER_M, 3)],
            "outline_count": len(results),
            "outlines_with_native_band_cells": sum(row["native_cells_200_300ft_below_navd88"] > 0 for row in results),
            "total_native_band_cells": sum(row["native_cells_200_300ft_below_navd88"] for row in results),
            "followup_order_context_ids": [row["context_id"] for row in sorted(
                results, key=lambda row: (not bool(row["historical_camera_windows"]),
                                          -row["native_cells_200_300ft_below_navd88"],
                                          row["context_id"]))],
            "outlines": results, "fishing_target": False, "exportable": False,
            "limitations": [
                "NAVD88 is not MLLW; this comparison band cannot establish a legal 200–300 ft fishing depth.",
                "The original USGS product lacks per-cell uncertainty, so no 300 ft candidate passes depth qualification.",
                "Pixels are counted within generalized hard-bottom outlines, not converted into chartplotter points or independently verified catches.",
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--prior", type=Path, default=Path("dist/data/usgs-offshore-monterey-bathy-context-review.json"))
    parser.add_argument("--queue", type=Path, default=Path("dist/data/monterey-300-native-research-queue.json"))
    parser.add_argument("--context", type=Path, default=Path("dist/data/usgs-offshore-monterey-hard-context.geojson"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.archive, json.loads(args.prior.read_text()), json.loads(args.queue.read_text()),
                   json.loads(args.context.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['outlines_with_native_band_cells']}/{result['outline_count']} outlines have original NAVD88 band pixels; zero fishing targets")


if __name__ == "__main__":
    main()

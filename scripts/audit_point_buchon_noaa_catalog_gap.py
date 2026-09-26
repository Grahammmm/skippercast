#!/usr/bin/env python3
"""Query NOAA's NOS BAG catalog around measured USGS Point Buchon rock cells.

The query envelope is deliberately broader than the cells. A catalog polygon
intersection is a discovery lead, not measured overlap or a fishing coordinate.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from scripts.audit_point_buchon_original_pair import (
    EXPECTED_BATHY, EXPECTED_CLASS, LOWER_M, UPPER_M, original_tiff,
)
from scripts.discover_noaa_surveys import scan


def outward(value, up):
    return (math.ceil(value * 100000) if up else math.floor(value * 100000)) / 100000


def hard_rugose_envelope(bathy_zip, character_zip):
    low_x = low_y = float("inf")
    high_x = high_y = float("-inf")
    cells = 0
    with rasterio.open(original_tiff(bathy_zip)) as bathy, rasterio.open(original_tiff(character_zip)) as character:
        if (bathy.shape != character.shape or bathy.transform != character.transform
                or str(bathy.crs) != "EPSG:32610" or character.crs != bathy.crs):
            raise ValueError("Point Buchon original depth and character grids no longer align")
        for _, window in bathy.block_windows(1):
            depth = bathy.read(1, window=window, masked=True)
            kind = character.read(1, window=window, masked=True)
            d, c = np.ma.getdata(depth), np.ma.getdata(kind)
            mask = (~np.ma.getmaskarray(depth) & ~np.ma.getmaskarray(kind)
                    & np.isfinite(d) & (-d >= LOWER_M) & (-d <= UPPER_M) & (c == 3))
            if not np.any(mask):
                continue
            rows, columns = np.nonzero(mask)
            cells += len(rows)
            corners = ((int(rows.min()), int(columns.min())),
                       (int(rows.max()), int(columns.max())))
            transform = bathy.window_transform(window)
            for row, column in corners:
                x, y = rasterio.transform.xy(transform, row, column, offset="center")
                low_x, high_x = min(low_x, x), max(high_x, x)
                low_y, high_y = min(low_y, y), max(high_y, y)
        if cells != 804337:
            raise ValueError("Original Point Buchon hard/rugose 200–300 ft cell count changed")
        west, south, east, north = transform_bounds(bathy.crs, "EPSG:4326", low_x, low_y, high_x, high_y)
    return cells, [outward(west, False), outward(south, False),
                   outward(east, True), outward(north, True)]


def build(bathy_zip, character_zip, deep_receipt, scan_fn=scan):
    cells, bounds = hard_rugose_envelope(bathy_zip, character_zip)
    catalog = scan_fn([{"id": "point-buchon-original-hard-rugose-envelope", "bounds": bounds}])
    if catalog.get("health", {}).get("status") != "ok" or len(catalog.get("sectors", [])) != 1:
        raise ValueError("Fresh NOAA survey-catalog query failed")
    query = catalog["sectors"][0]
    ids = sorted(row["id"] for row in query["surveys"])
    if ids != ["W00479"]:
        raise ValueError("NOAA catalog lead set changed; inspect before changing the source queue")
    source = next((row for row in deep_receipt["sources"] if row["survey_id"] == "W00479"), None)
    if (not source or source["native_refinements"]["cells_at_or_shallower_than_300ft"] != 0
            or source["vertical_datum"] != "MLLW" or deep_receipt["fishing_target"] is not False):
        raise ValueError("Original W00479 depth refutation missing or changed")
    return {
        "schema_version": 1,
        "scope": "point-buchon-noaa-survey-catalog-envelope-gap",
        "usgs_bathymetry_archive_sha256": EXPECTED_BATHY,
        "usgs_character_archive_sha256": EXPECTED_CLASS,
        "nominal_source_datum_depth_band_ft": [200, 300],
        "original_hard_rugose_cells": cells,
        "query_envelope_wgs84": bounds,
        "catalog_service": catalog["source_url"],
        "request_url": query["request_url"],
        "response_sha256": query["raw_sha256"],
        "bag_survey_ids_returned": ids,
        "only_returned_survey_original_depth_receipt": "dist/data/central-deep-original-300-refutation.json",
        "only_returned_survey_shallowest_measured_depth_m_mllw": source["native_refinements"]["shallowest_depth_m_mllw"],
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
        "limitation": "This is one NOS catalog envelope query, not an exhaustive inventory or a cellwise USGS/NOAA overlap. The USGS 200–300 ft band is source-datum only; no chart datum, upper uncertainty, legal access, navigation or biological spot validation is established.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bathy", type=Path, default=Path("var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon.zip"))
    parser.add_argument("--character", type=Path, default=Path("var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip"))
    parser.add_argument("--deep-receipt", type=Path, default=Path("dist/data/central-deep-original-300-refutation.json"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/point-buchon-noaa-catalog-envelope-gap.json"))
    args = parser.parse_args()
    report = build(args.bathy, args.character, json.loads(args.deep_receipt.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["original_hard_rugose_cells"], report["bag_survey_ids_returned"])


if __name__ == "__main__":
    main()

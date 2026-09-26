#!/usr/bin/env python3
"""Intersect original Monterey depth and character pixels in 200–300 ft NAVD88.

Nearest-neighbor reprojection aligns the original 2 m character and depth
rasters for research triage only. Their horizontal realizations/epochs and
vertical-depth uncertainty do not support a chartplotter fishing coordinate.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask
from rasterio.vrt import WarpedVRT
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from scripts.build_monterey_300_research_queue import LOWER_M, UPPER_M
from scripts.build_usgs_statewide_context import hard_class_review


def original_tiff(archive):
    with zipfile.ZipFile(archive) as source:
        paths = [name for name in source.namelist() if name.lower().endswith(".tif")]
        if len(paths) != 1:
            raise ValueError("Expected one original GeoTIFF in USGS archive")
        return f"zip://{archive.resolve()}!{paths[0]}"


def paired_count(depth, character):
    if depth.shape != character.shape:
        raise ValueError("Original grids are not pixel-aligned after reprojection")
    elevations = np.ma.getdata(depth)
    codes = np.ma.getdata(character)
    measured = ~np.ma.getmaskarray(depth) & np.isfinite(elevations)
    band = measured & (-elevations >= LOWER_M) & (-elevations <= UPPER_M)
    class_valid = band & ~np.ma.getmaskarray(character)
    # The reviewed original XML defines class 3 as rugose rock/boulder; tens
    # encode depth and slope zones in this categorical product.
    hard = class_valid & (codes.astype("int64") % 10 == 3)
    return {"native_navd88_band_cells": int(np.count_nonzero(band)),
            "original_character_present_in_band_cells": int(np.count_nonzero(class_valid)),
            "paired_original_class3_hard_band_cells": int(np.count_nonzero(hard)),
            "paired_hard_area_m2_at_2m_grid": int(np.count_nonzero(hard)) * 4}


def audit(bathy_zip, class_zip, pixel, context, metadata):
    bathy_hash = hashlib.sha256(bathy_zip.read_bytes()).hexdigest()
    class_hash = hashlib.sha256(class_zip.read_bytes()).hexdigest()
    source = next((row for row in metadata["records"] if row.get("block_id") == "OffshoreMonterey"
                   and row.get("kind") == "seafloor_character" and row.get("status") == "ok"
                   and "2m_OffshoreMonterey" in row.get("metadata_url", "")), None)
    if (not source or not hard_class_review(source)
            or bathy_hash != pixel["source_archive_sha256"]
            or class_hash != "8ca813f1fbfd7afb231914d7a9ebdb5667559bf0172a2024f3d45e9180d94e08"
            or pixel.get("native_vertical_datum") != "NAVD88"
            or pixel.get("fishing_target") is not False):
        raise ValueError("Original paired USGS source or class definition changed")
    features = {feature["properties"]["id"]: feature for feature in context["features"]}
    rows = []
    with rasterio.open(original_tiff(bathy_zip)) as bathy, rasterio.open(original_tiff(class_zip)) as character:
        if (str(bathy.crs) != "EPSG:26910" or str(character.crs) != "EPSG:32610"
                or any(abs(r - 2) > .01 for r in bathy.res + character.res)
                or bathy.count != 1 or character.count != 1):
            raise ValueError("Unexpected original raster reference frame or 2 m resolution")
        project = Transformer.from_crs("EPSG:4326", bathy.crs, always_xy=True).transform
        with WarpedVRT(character, crs=bathy.crs, transform=bathy.transform,
                       width=bathy.width, height=bathy.height,
                       resampling=Resampling.nearest) as paired:
            for item in pixel["outlines"]:
                ident = item["context_id"]
                feature = features.get(ident)
                if (not feature or feature["properties"].get("source_file_sha256") != class_hash
                        or feature["properties"].get("source_metadata_sha256") != source["xml_sha256"]):
                    raise ValueError("Research outline provenance changed")
                polygon = transform(project, shape(feature["geometry"]))
                elevation, _ = mask(bathy, [mapping(polygon)], crop=True, filled=False)
                classes, _ = mask(paired, [mapping(polygon)], crop=True, filled=False)
                counts = paired_count(elevation[0], classes[0])
                if counts["native_navd88_band_cells"] != item["native_cells_200_300ft_below_navd88"]:
                    raise ValueError(f"Original depth-band cells changed for {ident}")
                rows.append({"context_id": ident, **counts,
                             "historical_camera_windows": item["historical_camera_windows"],
                             "historical_rockfish_positive_windows": item["historical_rockfish_positive_windows"],
                             "fishing_target": False, "exportable": False})
    ordered = sorted(rows, key=lambda row: (not bool(row["historical_camera_windows"]),
                                             -row["paired_original_class3_hard_band_cells"],
                                             row["context_id"]))
    return {"schema_version": 1, "scope": "monterey-original-paired-hard-depth-band-audit",
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "bathymetry_archive_sha256": bathy_hash, "character_archive_sha256": class_hash,
            "character_metadata_sha256": source["xml_sha256"],
            "native_depth_vertical_datum": "NAVD88", "native_resolution_m": 2,
            "comparison_band_m_below_navd88": [round(LOWER_M, 3), round(UPPER_M, 3)],
            "outline_count": len(rows),
            "original_band_cells_in_outlines": sum(row["native_navd88_band_cells"] for row in rows),
            "paired_class3_hard_band_cells": sum(row["paired_original_class3_hard_band_cells"] for row in rows),
            "followup_order_context_ids": [row["context_id"] for row in ordered],
            "outlines": rows, "fishing_target": False, "exportable": False,
            "limitations": [
                "Original USGS class 3 denotes interpreted rugose rock/boulder, not individual boulder dimensions or fish abundance.",
                "Nearest-neighbor EPSG:32610-to-EPSG:26910 alignment does not resolve the source horizontal realization or epoch; no exact waypoint follows.",
                "NAVD88 is not MLLW and the source lacks per-cell bathymetric uncertainty; 200–300 ft fishing-depth qualification remains blocked.",
                "These are source pixels inside generalized historical outlines; full source coverage, current rules, MPAs, access, ENC and route remain separate checks.",
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bathy", type=Path, required=True)
    parser.add_argument("--character", type=Path, required=True)
    parser.add_argument("--pixel", type=Path, default=Path("dist/data/monterey-original-300-pixel-review.json"))
    parser.add_argument("--context", type=Path, default=Path("dist/data/usgs-offshore-monterey-hard-context.geojson"))
    parser.add_argument("--metadata", type=Path, default=Path("dist/data/usgs-csmp-map-metadata.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.bathy, args.character, json.loads(args.pixel.read_text()),
                   json.loads(args.context.read_text()), json.loads(args.metadata.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['paired_class3_hard_band_cells']} original paired class-3 pixels; zero fishing targets")


if __name__ == "__main__":
    main()

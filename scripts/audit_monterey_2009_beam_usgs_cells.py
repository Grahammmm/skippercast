#!/usr/bin/env python3
"""Join original 2009 Monterey GSF beams to paired USGS 2 m source cells.

This is a nearest-cell *research* comparison. Unknown GSF tidal datum,
source registration and shared NOAA-merge lineage prohibit fishing marks.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from shapely.geometry import mapping, shape
from shapely.ops import transform as transform_geometry

from scripts.audit_monterey_2009_ncei_valid_beams import (
    BASE, PROCESSED, ROOT, decode_line, file_name, read_pinned,
)
from scripts.audit_usgs_monterey_300_paired import original_tiff


BATHY_URL = "https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/data/Bathymetry_2m_OffshoreMonterey.zip"
BATHY_SHA = "2a769bc2bb343f6df5041ad7cab7bfcfe3eb641e2ef0bba7f3709edcd07c17f1"
CHAR_URL = "https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/data/SeafloorCharacter_2m_OffshoreMonterey.zip"
CHAR_SHA = "8ca813f1fbfd7afb231914d7a9ebdb5667559bf0172a2024f3d45e9180d94e08"
LOWER, UPPER = 60.96, 91.44


def ensure_archive(path, url, expected, limit, fetch):
    if fetch and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".partial")
        digest, size = hashlib.sha256(), 0
        request = Request(url, headers={"User-Agent": "SkipperCast-original-cell-audit/1.0"})
        try:
            with urlopen(request, timeout=300) as response, temp.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("USGS archive exceeds download bound")
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != expected:
                raise ValueError("USGS archive changed during download")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError("USGS archive exceeds size bound")
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("USGS original source bytes changed")


def join_outline(lon, lat, source_depth, polygon, bathy, character):
    if not (len(lon) == len(lat) == len(source_depth)) or not len(lon):
        raise ValueError("Original beam arrays missing")
    x, y = Transformer.from_crs("EPSG:4326", bathy.crs, always_xy=True).transform(lon, lat)
    transform = bathy.transform
    col = np.floor((x - transform.c) / transform.a).astype("i4")
    row = np.floor((y - transform.f) / transform.e).astype("i4")
    inside = (row >= 0) & (row < bathy.height) & (col >= 0) & (col < bathy.width)
    if not np.all(inside):
        raise ValueError("Research-outline beam outside original USGS grid")
    # Read only the measured patch window. No beam coordinates enter the receipt.
    r0, r1 = max(0, int(row.min()) - 1), min(bathy.height, int(row.max()) + 2)
    c0, c1 = max(0, int(col.min()) - 1), min(bathy.width, int(col.max()) + 2)
    window = Window(c0, r0, c1 - c0, r1 - r0)
    depth_grid = bathy.read(1, window=window, masked=True)
    class_grid = character.read(1, window=window, masked=True)
    if depth_grid.shape != class_grid.shape:
        raise ValueError("Paired USGS window is not aligned")
    projected_polygon = transform_geometry(
        Transformer.from_crs("EPSG:4326", bathy.crs, always_xy=True).transform, polygon)
    centers_inside_outline = geometry_mask(
        [mapping(projected_polygon)], out_shape=depth_grid.shape,
        transform=rasterio.windows.transform(window, bathy.transform),
        invert=True, all_touched=False)
    local_row, local_col = row - r0, col - c0
    elevations = depth_grid[local_row, local_col]
    classes = class_grid[local_row, local_col]
    valid_depth = ~np.ma.getmaskarray(elevations) & np.isfinite(np.ma.getdata(elevations))
    valid_class = ~np.ma.getmaskarray(classes)
    band = valid_depth & (-np.ma.getdata(elevations) >= LOWER) & (-np.ma.getdata(elevations) <= UPPER)
    hard = valid_class & (np.ma.getdata(classes).astype("i4") % 10 == 3)
    center_inside = centers_inside_outline[local_row, local_col]
    both = band & hard & center_inside
    unique_all = np.unique(row.astype("i8") * bathy.width + col.astype("i8"))
    unique_center_inside = np.unique(row[center_inside].astype("i8") * bathy.width + col[center_inside].astype("i8"))
    unique_paired = np.unique((row[both].astype("i8") * bathy.width + col[both].astype("i8")))
    differences = source_depth[both] - (-np.ma.getdata(elevations)[both])
    # Cell-neighborhood robustness is a sensitivity check, not a registration
    # bound: an unknown real offset may exceed one 2 m cell.
    core = ((local_row >= 1) & (local_row < depth_grid.shape[0] - 1)
            & (local_col >= 1) & (local_col < depth_grid.shape[1] - 1))
    robust = core.copy()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            rr = np.clip(local_row + dr, 0, depth_grid.shape[0] - 1)
            cc = np.clip(local_col + dc, 0, depth_grid.shape[1] - 1)
            elevations_n = depth_grid[rr, cc]
            classes_n = class_grid[rr, cc]
            robust &= (~np.ma.getmaskarray(elevations_n)
                       & np.isfinite(np.ma.getdata(elevations_n))
                       & (-np.ma.getdata(elevations_n) >= LOWER)
                       & (-np.ma.getdata(elevations_n) <= UPPER)
                       & ~np.ma.getmaskarray(classes_n)
                       & (np.ma.getdata(classes_n).astype("i4") % 10 == 3)
                       & centers_inside_outline[rr, cc])
    unique_robust = np.unique(row[robust].astype("i8") * bathy.width + col[robust].astype("i8"))
    return {
        "source_valid_beams_inside_outline": int(len(lon)),
        "source_valid_beams_nearest_usgs_cell_center_inside_outline": int(center_inside.sum()),
        "source_valid_beams_on_populated_usgs_depth_cells": int(valid_depth.sum()),
        "source_valid_beams_on_usgs_navd88_200_300ft_cells": int(band.sum()),
        "source_valid_beams_on_paired_usgs_class3_200_300ft_cells": int(both.sum()),
        "source_valid_beams_on_3x3_stable_class3_band_cells": int(robust.sum()),
        "unique_usgs_2m_cells_under_source_beams": int(len(unique_all)),
        "unique_usgs_2m_cell_centers_inside_outline_under_source_beams": int(len(unique_center_inside)),
        "unique_paired_class3_band_cells_under_source_beams": int(len(unique_paired)),
        "unique_3x3_stable_class3_band_cells_under_source_beams": int(len(unique_robust)),
        "unknown_datum_gsf_minus_usgs_navd88_depth_median_m": round(float(np.median(differences)), 3) if len(differences) else None,
        "unknown_datum_gsf_minus_usgs_navd88_depth_p95_absolute_m": round(float(np.quantile(np.abs(differences), .95)), 3) if len(differences) else None,
        "mllw_depth_qualified": False,
        "horizontal_registration_qualified": False,
        "independent_substrate_qualified": False,
        "fishing_target": False,
        "exportable": False,
    }


def build(root, fetch=False):
    original = json.loads((root / "dist/data/monterey-2009-centralmontereybay-valid-beam-review.json").read_text())
    matrix_path = root / "dist/data/monterey-300-source-evidence-matrix.json"
    matrix = json.loads(matrix_path.read_text())
    if original.get("scope") != "monterey-2009-centralmontereybay-original-valid-beam-research" or original.get("fishing_target") is not False:
        raise ValueError("Original beam audit changed")
    features = {f["properties"]["id"]: f for f in json.loads((root / "dist/data/usgs-offshore-monterey-hard-context.geojson").read_text())["features"]}
    outlines = {ident: shape(features[row["context_id"]]["geometry"]) for ident, row in original["outlines"].items()}
    collected = defaultdict(lambda: {"lon": [], "lat": [], "depth": []})

    def collect(ident, lon, lat, depth):
        collected[ident]["lon"].append(lon)
        collected[ident]["lat"].append(lat)
        collected[ident]["depth"].append(depth)

    cache = root / "var/review/ncei-centralmontereybay-priority"
    for stem, spec in sorted(PROCESSED.items()):
        name = file_name(stem)
        path = cache / name
        read_pinned(path, BASE + name, spec[1], fetch, 30_000_000)
        companion_base = BASE + "generated/" + name.removesuffix(".gz")
        inf = read_pinned(cache / (name.removesuffix(".gz") + ".inf"), companion_base + ".inf", spec[2], fetch, 1_000_000)
        fnv = read_pinned(cache / (name.removesuffix(".gz") + ".fnv"), companion_base + ".fnv", spec[3], fetch, 2_000_000)
        _, rows, _, _ = decode_line(path, inf, fnv, spec, outlines, collect=collect)
        prior = next(item for item in original["lines"] if item["ncei_file_id"] == spec[0])
        if any(rows[ident]["valid_beams_inside_outline"] != prior["outlines"][ident]["valid_beams_inside_outline"] for ident in outlines):
            raise ValueError("Original beam counts changed")

    bathy_zip, class_zip = root / "var/review/Bathymetry_2m_OffshoreMonterey.zip", root / "var/review/SeafloorCharacter_2m_OffshoreMonterey.zip"
    ensure_archive(bathy_zip, BATHY_URL, BATHY_SHA, 250_000_000, fetch)
    ensure_archive(class_zip, CHAR_URL, CHAR_SHA, 10_000_000, fetch)
    summaries = {}
    with rasterio.open(original_tiff(bathy_zip)) as bathy, rasterio.open(original_tiff(class_zip)) as raw_character:
        if (str(bathy.crs) != "EPSG:26910" or str(raw_character.crs) != "EPSG:32610"
                or any(abs(value - 2) > .01 for value in bathy.res + raw_character.res)):
            raise ValueError("USGS native raster frame or resolution changed")
        with WarpedVRT(raw_character, crs=bathy.crs, transform=bathy.transform,
                       width=bathy.width, height=bathy.height, resampling=Resampling.nearest) as character:
            for ident in sorted(outlines):
                points = {key: np.concatenate(collected[ident][key]) for key in ("lon", "lat", "depth")}
                if len(points["lon"]) != original["outlines"][ident]["valid_beams_inside_outline"]:
                    raise ValueError("Original source outline tally changed")
                summaries[ident] = {"context_id": original["outlines"][ident]["context_id"],
                                    **join_outline(points["lon"], points["lat"], points["depth"], outlines[ident], bathy, character)}
    reviewed = {row["context_id"]: row for row in matrix["review_order"]}
    for row in summaries.values():
        prior = reviewed[row["context_id"]]
        if (row["unique_usgs_2m_cell_centers_inside_outline_under_source_beams"] > prior["native_navd88_band_cells"]
                or row["unique_paired_class3_band_cells_under_source_beams"] > prior["paired_original_class3_hard_band_cells"]):
            raise ValueError("Beam-to-cell join exceeds original measured outline cells")
    return {
        "schema_version": 1, "scope": "monterey-2009-original-beams-to-usgs-native-cell-screen",
        "original_beam_receipt_sha256": hashlib.sha256((root / "dist/data/monterey-2009-centralmontereybay-valid-beam-review.json").read_bytes()).hexdigest(),
        "original_usgs_outline_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "usgs_bathymetry_sha256": BATHY_SHA, "usgs_character_sha256": CHAR_SHA,
        "method": "Original processed valid GSF beams projected to nearest native USGS 2 m bathymetry cell; original seafloor character resampled nearest-neighbor to that grid. 3x3 is a one-cell sensitivity diagnostic, not a positional confidence interval.",
        "outlines": summaries, "fishing_target": False, "exportable": False,
        "next_acquisition": "Resolve 2009 source tide/datum and output TPU, source-to-2013-merge lineage, horizontal registration and independent substrate/fish observations before full-footprint MLLW and legal/route screening.",
        "limitations": [
            "GSF TIDAL_DATUM=UNKNOWN; its depths are not directly comparable to USGS NAVD88 or chart MLLW. The reported difference is diagnostic only, not a survey error estimate.",
            "USGS 2 m bathymetry is a NOAA 2013 merge resample and may reuse the 2009 GSF survey; this pairing is not independent corroboration.",
            "USGS seafloor character is an interpreted class with unverified source-to-GSF registration; nearest and 3x3 matches do not prove a rock pile, boulder size or fish presence.",
            "No chart-depth, uncertainty, MPA/legal, ENC, access-route or current catch gate is cleared. No source beam positions or fishing coordinates are published.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/data/monterey-2009-beam-usgs-cell-screen.json"))
    args = parser.parse_args()
    report = build(args.root.resolve(), args.fetch)
    if args.verify:
        previous = json.loads(args.verify.read_text())
        if report != {key: value for key, value in previous.items() if key != "checked_at"}:
            raise ValueError("Original-to-USGS cell comparison changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("Original Monterey beams compared with USGS 2 m cells; zero fishing targets")


if __name__ == "__main__":
    main()

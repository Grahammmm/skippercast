#!/usr/bin/env python3
"""Audit BlueTopo contributor pixels at original Point Buchon research cells.

This is a nominal cross-product center match. Its counts cannot establish
survey registration, charted depth, an individual rock, or a fishing target.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

import numpy as np
import rasterio
from rasterio.warp import transform

from scripts.audit_nbs_modeling_tile import contributors, is_measured_survey, sha256, verified_file
from scripts.audit_point_buchon_original_pair import (
    EXPECTED_BATHY, EXPECTED_CLASS, LOWER_M, UPPER_M, original_tiff,
)


SCHEME_SHA = "62db77bda8ce8deea24b4824c78e204f727ff434f1d91450cb8acfea5e188dcc"
SCHEME_URL = "https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_20260924_191855.gpkg"
EXPECTED_TILES = {"BH4575BS", "BH4585BS", "BH4595BS", "BH4575BT", "BH4585BT",
                  "BH4595BT", "BH4575BV", "BH4585BV"}


def source_centers(bathy_zip, character_zip):
    xs, ys = [], []
    with rasterio.open(original_tiff(bathy_zip)) as bathy, rasterio.open(original_tiff(character_zip)) as character:
        if (bathy.shape != character.shape or bathy.transform != character.transform
                or str(bathy.crs) != "EPSG:32610" or character.crs != bathy.crs):
            raise ValueError("Point Buchon original USGS grids changed")
        for _, window in bathy.block_windows(1):
            depth = bathy.read(1, window=window, masked=True)
            kind = character.read(1, window=window, masked=True)
            d, c = np.ma.getdata(depth), np.ma.getdata(kind)
            selected = (~np.ma.getmaskarray(depth) & ~np.ma.getmaskarray(kind)
                        & np.isfinite(d) & (-d >= LOWER_M) & (-d <= UPPER_M) & (c == 3))
            if not np.any(selected):
                continue
            rows, columns = np.nonzero(selected)
            affine = bathy.window_transform(window)
            xs.append(affine.c + (columns + .5) * affine.a)
            ys.append(affine.f + (rows + .5) * affine.e)
    x, y = np.concatenate(xs), np.concatenate(ys)
    if len(x) != 804337:
        raise ValueError("Original USGS nominal hard/rugose cell count changed")
    return x, y


def tile_rows(scheme, envelope):
    if sha256(scheme) != SCHEME_SHA:
        raise ValueError("NOAA BlueTopo tile scheme changed")
    west, south, east, north = envelope
    with sqlite3.connect(scheme) as db:
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or table[0] != "BlueTopo_Tile_Scheme_20260924_191855":
            raise ValueError("Unexpected BlueTopo tile scheme")
        name = table[0]
        rtree = "rtree_" + name + "_geom"
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(
            f'SELECT t.tile,t.GeoTIFF_Link,t.GeoTIFF_SHA256_Checksum,t.RAT_Link,t.RAT_SHA256_Checksum '
            f'FROM "{name}" t JOIN "{rtree}" r ON t.fid=r.id '
            'WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=? ORDER BY t.tile',
            (west, east, south, north))]
    if {row["tile"] for row in rows} != EXPECTED_TILES:
        raise ValueError("BlueTopo tiles across Point Buchon changed")
    return rows


def build(scheme, bathy_zip, character_zip, envelope_receipt, cache, fetch=False):
    if (envelope_receipt.get("scope") != "point-buchon-noaa-survey-catalog-envelope-gap"
            or envelope_receipt.get("original_hard_rugose_cells") != 804337
            or envelope_receipt.get("usgs_bathymetry_archive_sha256") != EXPECTED_BATHY
            or envelope_receipt.get("usgs_character_archive_sha256") != EXPECTED_CLASS):
        raise ValueError("Point Buchon source-cell envelope changed")
    verified_file(SCHEME_URL, SCHEME_SHA, scheme, fetch, max_bytes=10_000_000)
    x, y = source_centers(bathy_zip, character_zip)
    # This is a nominal horizontal transform, not a resolved epoch/registration.
    xx, yy = transform("EPSG:32610", "EPSG:26910", x, y)
    xx, yy = np.asarray(xx), np.asarray(yy)
    assigned = np.zeros(len(x), dtype=bool)
    counts = Counter()
    measured_dates = {}
    tile_receipts = []
    measured_pixels = 0
    for row in tile_rows(scheme, envelope_receipt["query_envelope_wgs84"]):
        tile = row["tile"]
        raster_path = cache / f"{tile}.tiff"
        rat_path = cache / f"{tile}.tiff.aux.xml"
        raster_sha = verified_file(row["GeoTIFF_Link"], row["GeoTIFF_SHA256_Checksum"],
                                   raster_path, fetch, max_bytes=15_000_000)
        rat_sha = verified_file(row["RAT_Link"], row["RAT_SHA256_Checksum"],
                                rat_path, fetch, max_bytes=3_000_000)
        rat = contributors(rat_path)
        with rasterio.open(raster_path) as raster:
            if (raster.descriptions != ("Elevation", "Uncertainty", "Contributor")
                    or "navd88" not in raster.crs.to_wkt().lower()
                    or abs(raster.transform.a - 4) > .001 or abs(raster.transform.e + 4) > .001
                    or raster.transform.b or raster.transform.d):
                raise ValueError("BlueTopo raster grid or datum changed")
            rr = np.floor((raster.transform.f - yy) / 4).astype("int64")
            cc = np.floor((xx - raster.transform.c) / 4).astype("int64")
            inside = (rr >= 0) & (cc >= 0) & (rr < raster.height) & (cc < raster.width)
            ids = np.nonzero(inside & ~assigned)[0]
            if len(ids):
                bands = raster.read()
                elev, unc, code = bands[:, rr[ids], cc[ids]]
                valid = np.isfinite(elev) & np.isfinite(unc) & np.isfinite(code)
                ids, code = ids[valid], code[valid].astype("int64")
                unknown = set(np.unique(code)) - set(rat)
                if unknown:
                    raise ValueError(f"Unidentified BlueTopo contributor codes in {tile}: {unknown}")
                assigned[ids] = True
                for key, count in Counter(int(value) for value in code).items():
                    source = rat[key]["source_survey_id"]
                    counts[source] += count
                    if is_measured_survey(rat[key]):
                        measured_pixels += count
                        measured_dates[source] = rat[key]["survey_date_end"]
        tile_receipts.append({"tile_id": tile, "raster_url": row["GeoTIFF_Link"],
                              "raster_sha256": raster_sha, "rat_url": row["RAT_Link"],
                              "rat_sha256": rat_sha})
    return {"schema_version": 1, "scope": "point-buchon-original-hard-cells-bluetopo-contributor-overlap",
            "scheme_url": SCHEME_URL, "scheme_sha256": SCHEME_SHA,
            "usgs_bathymetry_archive_sha256": EXPECTED_BATHY,
            "usgs_character_archive_sha256": EXPECTED_CLASS,
            "source_envelope_receipt": "dist/data/point-buchon-noaa-catalog-envelope-gap.json",
            "nominal_source_datum_depth_band_ft": [200, 300],
            "original_usgs_hard_rugose_cell_centers": len(x),
            "bluetopo_cells_with_finite_elevation_uncertainty_and_contributor": int(assigned.sum()),
            "bluetopo_measured_survey_contributor_centers": measured_pixels,
            "measured_source_dates": dict(sorted(measured_dates.items())),
            "contributor_center_counts": dict(sorted(counts.items())),
            "tiles": tile_receipts,
            "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
            "limitation": "BlueTopo is a compiled NAVD88 raster. These are nominal 2 m USGS center-to-4 m BlueTopo cell matches without resolved survey epoch or horizontal registration. Contributor codes identify source lineage, not independent rock groundtruth, validated MLLW depth or navigable fishing patches."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheme", type=Path, default=Path("var/review/BlueTopo_Tile_Scheme_20260924_191855.gpkg"))
    parser.add_argument("--bathy", type=Path, default=Path("var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon.zip"))
    parser.add_argument("--character", type=Path, default=Path("var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip"))
    parser.add_argument("--envelope", type=Path, default=Path("dist/data/point-buchon-noaa-catalog-envelope-gap.json"))
    parser.add_argument("--cache", type=Path, default=Path("var/review/bluetopo-point-buchon-rat"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/data/point-buchon-bluetopo-hard-cell-overlap.json"))
    args = parser.parse_args()
    report = build(args.scheme, args.bathy, args.character, json.loads(args.envelope.read_text()), args.cache, args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["bluetopo_measured_survey_contributor_centers"], report["original_usgs_hard_rugose_cell_centers"])


if __name__ == "__main__":
    main()

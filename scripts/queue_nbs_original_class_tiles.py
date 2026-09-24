"""Prioritize NOAA source tiles intersecting an original USGS hard-class grid.

An acquisition queue is not measured MLLW depth, legal access or a waypoint.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import box, mapping
from shapely.ops import transform

from scripts.audit_nbs_modeling_tile import sha256
from scripts.qualify_regular_bag_hard import original_character


def intersecting_scheme_rows(scheme, bounds, *, maximum=250):
    west, south, east, north = bounds
    if not (-125 <= west < east <= -116 and 32 <= south < north <= 42):
        raise ValueError("Original class footprint is outside California")
    with sqlite3.connect(scheme) as db:
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or not table[0].startswith("Modeling_Tile_Scheme_"):
            raise ValueError("Wrong NOAA NBS Modeling tile scheme")
        t = table[0]
        db.row_factory = sqlite3.Row
        rows = db.execute(
            f'SELECT t.tile,t.Resolution,t.GeoTIFF_Link,t.RAT_Link,r.minx,r.miny,r.maxx,r.maxy '
            f'FROM "{t}" t JOIN "rtree_{t}_geom" r ON t.fid=r.id '
            'WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=? '
            'ORDER BY t.tile', (west, east, south, north)).fetchall()
    if len(rows) > maximum:
        raise ValueError("Original class footprint produced too many NOAA tile leads")
    return [dict(row) for row in rows]


def queue(release_id, audit, metadata, scheme, usgs_cache):
    if audit.get("scope") != "usgs-state-waters-doi-native-grid-audit":
        raise ValueError("Original USGS DOI native audit required")
    rows = [row for row in audit["products"] if row.get("release_id") == release_id
            and row.get("kind") == "seafloor_character" and row.get("status") == "ok"]
    if len(rows) != 1:
        raise ValueError("Expected one audited original USGS seafloor-character grid")
    original = rows[0]
    uri = original_character(original, usgs_cache, metadata)
    with rasterio.open(uri) as raster:
        if raster.count != 1 or not raster.crs or not 1.5 <= max(raster.res) <= 5.1:
            raise ValueError("USGS original class raster is unsupported")
        to_wgs = Transformer.from_crs(raster.crs, "EPSG:4326", always_xy=True).transform
        to_native = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True).transform
        native_footprint = box(*raster.bounds)
        bounds = transform(to_wgs, native_footprint).bounds
        candidates = intersecting_scheme_rows(scheme, bounds)
        results = []
        for row in candidates:
            if not row["GeoTIFF_Link"] or not row["RAT_Link"]:
                continue
            resolution = row["Resolution"]
            if not resolution or not resolution.endswith("m") or not 0 < float(resolution[:-1]) <= 4:
                continue
            envelope = box(row["minx"], row["miny"], row["maxx"], row["maxy"])
            clipped = transform(to_native, envelope).intersection(native_footprint)
            if clipped.is_empty or clipped.area <= 0:
                continue
            window = from_bounds(*clipped.bounds, transform=raster.transform).round_offsets().round_lengths()
            window = window.intersection(rasterio.windows.Window(0, 0, raster.width, raster.height))
            cells = raster.read(1, window=window, masked=True)
            within_tile = geometry_mask([mapping(clipped)], out_shape=cells.shape,
                                        transform=raster.window_transform(window), invert=True)
            hard = (within_tile & ~np.ma.getmaskarray(cells) & (cells.data == 3))
            results.append({"tile": row["tile"], "tile_envelope_wgs84": [row["minx"], row["miny"], row["maxx"], row["maxy"]],
                            "tile_resolution_m": float(resolution[:-1]),
                            "class3_pixels_in_envelope": int(hard.sum()),
                            "class3_pixel_area_m2_upper_bound": round(float(hard.sum() * raster.res[0] * raster.res[1])),
                            "has_published_raster_and_rat": True})
    results.sort(key=lambda item: (-item["class3_pixels_in_envelope"], item["tile"]))
    return {"schema_version": 1, "scope": "original-usgs-hard-class-noaa-tile-acquisition-queue",
            "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "release_id": release_id, "usgs_original_archive_sha256": original["archive_sha256"],
            "usgs_original_metadata_sha256": original["metadata_sha256"], "noaa_scheme_sha256": sha256(scheme),
            "candidate_tiles": len(results), "ranked_tiles": results,
            "fishing_target": False, "exportable": False,
            "limitations": ["Counts are original historical USGS class-3 pixels inside NOAA tile envelopes, not overlap with measured NOAA cells.",
                            "An envelope can cross source gaps, MPAs and non-fishable depths; pixel-area figures are upper bounds and can repeat across adjacent tiles.",
                            "Each NOAA raster and RAT still needs its measured MLLW cell, age, uncertainty and depth screen, followed by exact hazards, current chart, legal areas and access."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--audit", type=Path, default=Path("var/usgs-doi-native-audit.json"))
    parser.add_argument("--metadata", type=Path, default=Path("var/usgs-doi-metadata.json"))
    parser.add_argument("--scheme", type=Path, default=Path("var/nbs-cache/modeling-tile-scheme.gpkg"))
    parser.add_argument("--usgs-cache", type=Path, default=Path("var/usgs-doi-native-cache"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = queue(args.release_id, json.loads(args.audit.read_text()), json.loads(args.metadata.read_text()),
                   args.scheme, args.usgs_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(args.release_id, result["candidate_tiles"], "source tile leads")


if __name__ == "__main__":
    main()

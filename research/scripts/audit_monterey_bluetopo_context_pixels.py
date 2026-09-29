#!/usr/bin/env python3
"""Trace BlueTopo contributor pixels inside 17 Monterey research outlines.

BlueTopo is a compiled NAVD88 source lead. Counts here are per tile and may
overlap at tile boundaries; they do not establish MLLW depth or a fish spot.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from skippercast.seafloor.io import sha256, verified_file

from research.scripts.audit_nbs_modeling_tile import contributors, is_measured_survey, item_year
from research.scripts.review_central_bluetopo_contributor_leads import SCHEME_SHA, SCHEME_URL


ROOT = Path(__file__).resolve().parents[2]
SCHEME = "var/review/BlueTopo_Tile_Scheme_20260924_191855.gpkg"
MATRIX = "dist/data/monterey-300-source-evidence-matrix.json"
CONTEXT = "dist/data/usgs-offshore-monterey-hard-context.geojson"
TILES = {"BC24S26W", "BH44P5CL", "BH44N5CK", "BH44P5CK", "BH44N5CJ"}


def tile_rows(scheme, geometries):
    if sha256(scheme) != SCHEME_SHA:
        raise ValueError("Official BlueTopo tile scheme changed")
    with sqlite3.connect(scheme) as db:
        db.row_factory = sqlite3.Row
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or table[0] != "BlueTopo_Tile_Scheme_20260924_191855":
            raise ValueError("Unexpected BlueTopo tile scheme table")
        name = table[0]
        found = {}
        for geom in geometries.values():
            west, south, east, north = geom.bounds
            rows = db.execute(
                f'SELECT t.tile,t.GeoTIFF_Link,t.GeoTIFF_SHA256_Checksum,t.RAT_Link,t.RAT_SHA256_Checksum '
                f'FROM "{name}" t JOIN "rtree_{name}_geom" r ON t.fid=r.id '
                'WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=?',
                (west, east, south, north))
            for row in rows:
                found[row["tile"]] = dict(row)
    if set(found) != TILES:
        raise ValueError("BlueTopo tiles intersecting Monterey research context changed")
    return [found[tile] for tile in sorted(found)]


def build(root, *, fetch=False):
    matrix_path, context_path = root / MATRIX, root / CONTEXT
    matrix, context = json.loads(matrix_path.read_text()), json.loads(context_path.read_text())
    order = matrix.get("review_order", [])
    if matrix.get("scope") != "monterey-300-source-evidence-review-matrix" or len(order) != 17:
        raise ValueError("Reviewed Monterey research set changed")
    ids = [item["context_id"] for item in order]
    if len(set(ids)) != 17 or context.get("scope") != "generalized-statewide-usgs-hard-bottom-context":
        raise ValueError("Monterey research context identity changed")
    feature_map = {f["properties"]["id"]: f for f in context["features"]}
    if any(ident not in feature_map for ident in ids):
        raise ValueError("Missing research context geometry")
    geometries = {ident: shape(feature_map[ident]["geometry"]) for ident in ids}
    scheme = root / SCHEME
    verified_file(SCHEME_URL, SCHEME_SHA, scheme, fetch, max_bytes=10_000_000)
    rows = {ident: {"context_id": ident, "tile_pixel_count": {},
                    "nominal_navd88_200_300ft_pixels_by_tile": {},
                    "measured_nominal_band_pixels_by_tile": {},
                    "nominal_band_contributors_by_tile": {}} for ident in ids}
    tile_receipts = []
    cache = root / "var/review/bluetopo-monterey-tile"
    for row in tile_rows(scheme, geometries):
        tile = row["tile"]
        raster_path, rat_path = cache / (tile + ".tiff"), cache / (tile + ".tiff.aux.xml")
        raster_hash = verified_file(row["GeoTIFF_Link"], row["GeoTIFF_SHA256_Checksum"],
                                    raster_path, fetch, max_bytes=20_000_000)
        rat_hash = verified_file(row["RAT_Link"], row["RAT_SHA256_Checksum"],
                                 rat_path, fetch, max_bytes=3_000_000)
        rat = contributors(rat_path)
        with rasterio.open(raster_path) as raster:
            if (raster.descriptions != ("Elevation", "Uncertainty", "Contributor")
                    or "navd88" not in raster.crs.to_wkt().lower()):
                raise ValueError("BlueTopo band identity or vertical datum changed")
            elevation, uncertainty, contributor = raster.read()
            project = Transformer.from_crs(4326, raster.crs, always_xy=True).transform
            footprint = box(*raster.bounds)
            for ident, geom in geometries.items():
                projected = transform(project, geom)
                if not projected.intersects(footprint):
                    continue
                mask = geometry_mask([mapping(projected)], out_shape=(raster.height, raster.width),
                                     transform=raster.transform, invert=True)
                valid = mask & np.isfinite(elevation) & np.isfinite(uncertainty) & np.isfinite(contributor)
                if not np.any(valid):
                    continue
                band = valid & (elevation <= -60.96) & (elevation >= -91.44)
                codes = Counter(int(value) for value in contributor[band])
                if set(codes) - set(rat):
                    raise ValueError("BlueTopo contributor code lacks official RAT identity")
                measured = sum(n for code, n in codes.items() if is_measured_survey(rat[code]))
                info = rows[ident]
                info["tile_pixel_count"][tile] = int(valid.sum())
                info["nominal_navd88_200_300ft_pixels_by_tile"][tile] = int(band.sum())
                info["measured_nominal_band_pixels_by_tile"][tile] = measured
                info["nominal_band_contributors_by_tile"][tile] = {
                    rat[code]["source_survey_id"]: {"pixels": count,
                        "measured": is_measured_survey(rat[code]),
                        "survey_date_end": rat[code]["survey_date_end"]}
                    for code, count in sorted(codes.items())}
        tile_receipts.append({"tile_id": tile, "raster_url": row["GeoTIFF_Link"],
                              "raster_sha256": raster_hash, "rat_url": row["RAT_Link"],
                              "rat_sha256": rat_hash})
    outlines = list(rows.values())
    measured_outlines = [r["context_id"] for r in outlines
                         if any(n > 0 for n in r["measured_nominal_band_pixels_by_tile"].values())]
    if (len(measured_outlines) != 2
            or sum(sum(r["measured_nominal_band_pixels_by_tile"].values()) for r in outlines) != 3
            or any(item_year(info["survey_date_end"]) >= 1940
                   for r in outlines for tile in r["nominal_band_contributors_by_tile"].values()
                   for info in tile.values() if info["measured"])):
        raise ValueError("Monterey BlueTopo original-pixel contributor result changed; review source")
    camera_ids = [item["context_id"] for item in order if item.get("historical_rockfish_positive_windows", 0) > 0]
    camera_measured = [ident for ident in camera_ids
                       if any(v > 0 for v in rows[ident]["measured_nominal_band_pixels_by_tile"].values())]
    priority_two = [order[i]["context_id"] for i in (0, 1)]
    if (len(camera_ids) != 4 or len(camera_measured) != 2
            or any(any(v > 0 for v in rows[ident]["measured_nominal_band_pixels_by_tile"].values())
                   for ident in priority_two)):
        raise ValueError("Camera-supported Monterey source-pixel status changed")
    return {"schema_version": 1,
            "scope": "monterey-17-research-outlines-bluetopo-pixel-contributor-screen",
            "scheme_url": SCHEME_URL, "scheme_sha256": SCHEME_SHA,
            "source_sha256": {"matrix": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
                              "context": hashlib.sha256(context_path.read_bytes()).hexdigest()},
            "research_outline_count": 17, "historical_rockfish_positive_outline_count": 4,
            "camera_positive_outlines_with_measured_nominal_band_pixels": 2,
            "highest_priority_two_camera_outlines_with_measured_nominal_band_pixels": 0,
            "outlines_with_any_measured_nominal_band_pixel": len(measured_outlines),
            "per_tile_measured_nominal_band_pixel_count": 3,
            "measured_nominal_band_survey_year_at_least_1940": False,
            "tiles": tile_receipts, "outlines": outlines,
            "full_original_cell_depth_and_uncertainty_verified": False,
            "fishing_target": False, "exportable": False,
            "limitations": "Per-tile center-pixel counts may overlap at raster tile boundaries and cannot be summed as unique chart cells. The 200–300 ft band is NAVD88, not MLLW. BlueTopo contributor labels show compilation lineage, not independent reef/fish evidence, original-source accuracy, legal access or navigable fishing spots."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/data/monterey-17-bluetopo-contributor-pixels.json"))
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = build(args.root.resolve(), fetch=args.fetch)
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if result != {key: value for key, value in saved.items() if key != "checked_at"}:
            raise ValueError("Monterey BlueTopo pixel lineage changed; review upstream surveys")
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("17 Monterey outlines; three old measured pixels, none on the two highest-priority camera contexts")


if __name__ == "__main__":
    main()

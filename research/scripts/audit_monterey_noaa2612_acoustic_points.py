#!/usr/bin/env python3
"""Audit acoustic-classified NOAA 2013 merge samples inside Monterey outlines.

This is a *lineage/support* audit, never a depth, legal, habitat or fishing
qualification. The COPC is part of the same 2013 merge family as the USGS 2 m
resample; point-class labels do not prove independent survey accuracy.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

import laspy
import numpy as np
import shapefile
from pyproj import Transformer
from shapely import contains_xy
from shapely.geometry import box, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[2]
BASE = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/2612/"
INDEX = "tileindex_2013_CA_TopoBathy_m2612.zip"
INDEX_SHA = "d926181c9c9d37f57b3bd816d33f2adc4be80fccc6542ff50362eea22131abc5"
TILE_SHA = {
    "20121123_10SEF895470.copc.laz": "c4e838d9665c5e96dbb2243bf7359dfcf3ca0444033ed8f44ff0e7110d2723fd",
    "20121123_10SEF895485.copc.laz": "9d053a6f161c72fda5c21a0ae4ee25886aef5768c3e5b8b81d2af26ca4ccd154",
    "20121123_10SEF910455.copc.laz": "b1d85921d512ad4d74b8a1ac2ed74d695b50d72aca09ed17667c4d8d13274716",
    "20121123_10SEF910470.copc.laz": "2a048898385b6c7f2b2a67a6b506c94132dc17c57320d10380b09ab5d2312e13",
    "20121123_10SEF910485.copc.laz": "b2f5eb1169c5ecc6483d04ecbb7ad7358421eb39debd129b9cf5768be083dc37",
    "20121123_10SEF910500.copc.laz": "6f8b60d325ff4ef3c9d84310f43c4e8a9ba8a416b5644ecad87aedcc62db1894",
    "20121123_10SEF910530.copc.laz": "2389424b644f6624687818ef3e7fc7422c24c9da77bccc651d449336f919bf96",
    "20121123_10SEF910545.copc.laz": "4afa1a816fc67b8a0b9168c03422262d1feff2c8c7444de4cce238e5d51593dc",
    "20121123_10SEF925455.copc.laz": "088da7c7fc16be560e51dedca030b19c4d3c216bf2c91632886e5840da19065b",
    "20121123_10SEF925470.copc.laz": "2b712dfb92cd752604f58db83edf85fe0044af8b97483c60cf00c0c61d09452d",
    "20121123_10SEF925545.copc.laz": "ea8e087b87aa3d18384f230acf56afafb2dc70205f835588bc6975ee675eb5bd",
    "20121123_10SEF925560.copc.laz": "5b0dcd4461b9c9bb8eec3e6a9496437e38f0d0430bc205deedd79e61b88e5965",
    "20121123_10SEF940560.copc.laz": "fb572a99dd323f2d4ea81192ee4412a2407d0b7be2e11b3fd4a64829ec132f21",
    "20121123_10SEF970545.copc.laz": "0502b069f330613acb321e313a86a1917f3ce3311389e25f886dff94649e7465",
    "20121123_10SEF970560.copc.laz": "977926ee278d75fb667ef64aa9fbd41f0c07521618232a9019b231f94eba2079",
    "20121123_10SEF970590.copc.laz": "ceb0ecc9e37bc7f5d0f499748cf0a9048066b83347096c71de501e3ac6dca36b",
    "20121123_10SEF970605.copc.laz": "6c3d1a628a912937d635065cfc4ef4e160218d0712e1cf42b837aa0949bcc90b",
    "20121123_10SEF985545.copc.laz": "e769774b2323a35e81545be7d8d791dc34feea19b7affc0c355a84363b179f4e",
}


def read_pinned(path, url, expected, fetch, max_bytes):
    if fetch and not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "SkipperCast-source-audit/1.0"})
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes or hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError(f"Official source changed or oversized: {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Pinned NOAA point-source missing or changed: {path.name}")


def index_reader(path):
    archive = zipfile.ZipFile(path)

    def item(suffix):
        return io.BytesIO(archive.read(next(n for n in archive.namelist() if n.endswith(suffix))))

    return shapefile.Reader(shp=item(".shp"), shx=item(".shx"), dbf=item(".dbf"))


def build(root, fetch=False):
    cache = root / "var/review/noaa2612-monterey"
    index_path = root / "var/review/noaa2612-tileindex.zip"
    read_pinned(index_path, BASE + INDEX, INDEX_SHA, fetch, 8_000_000)
    matrix_path = root / "research/receipts/monterey-300-source-evidence-matrix.json"
    context_path = root / "dist/data/usgs-offshore-monterey-hard-context.geojson"
    matrix = json.loads(matrix_path.read_text())
    if matrix.get("outline_count") != 17:
        raise ValueError("Monterey reviewed outline set changed")
    features = {f["properties"]["id"]: f for f in json.loads(context_path.read_text())["features"]}
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:3717", always_xy=True).transform
    outlines = {row["context_id"]: transform(to_utm, shape(features[row["context_id"]]["geometry"]))
                for row in matrix["review_order"]}
    memberships = {ident: [] for ident in outlines}
    official_urls = {}
    for record in index_reader(index_path).iterShapeRecords():
        tile = record.record[0]
        if not any(p.intersects(box(*record.shape.bbox)) for p in outlines.values()):
            continue
        if record.record[1] != "EPSG:3717" or record.record[2] != BASE + tile:
            raise ValueError(f"Unexpected tile CRS or URL: {tile}")
        if tile not in TILE_SHA:
            raise ValueError(f"New tile intersects Monterey research outlines: {tile}")
        official_urls[tile] = record.record[2]
        for ident, polygon in outlines.items():
            if polygon.intersects(box(*record.shape.bbox)):
                memberships[ident].append(tile)
    if set(official_urls) != set(TILE_SHA) or any(not v for v in memberships.values()):
        raise ValueError("Reviewed tile coverage changed")
    for tile, url in official_urls.items():
        read_pinned(cache / tile, url, TILE_SHA[tile], fetch, 70_000_000)

    result = {ident: {"class13_acoustic_points": 0, "class13_nominal_200_300ft_navd88_points": 0,
                      "class16_ignored_acoustic_points": 0, "source_ids": Counter(), "tile_names": []}
              for ident in outlines}
    for tile in sorted(official_urls):
        with laspy.open(cache / tile) as handle:
            header_crs = handle.header.parse_crs()
            if not header_crs or header_crs.sub_crs_list[0].to_epsg() != 3717 or header_crs.sub_crs_list[1].to_epsg() != 5703:
                raise ValueError(f"Unexpected point reference frame: {tile}")
            points = handle.read()
        x, y, z = points.x, points.y, points.z
        acoustic = np.asarray(points.classification) == 13
        ignored = np.asarray(points.classification) == 16
        source_ids = np.asarray(points.point_source_id)
        for ident, polygon in outlines.items():
            if tile not in memberships[ident]:
                continue
            minx, miny, maxx, maxy = polygon.bounds
            bounding = (x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy)
            if not np.any(bounding):
                continue
            indexes = np.flatnonzero(bounding)
            inside = contains_xy(polygon, x[indexes], y[indexes])
            indexes = indexes[inside]
            row = result[ident]
            row["tile_names"].append(tile)
            row["class13_acoustic_points"] += int(acoustic[indexes].sum())
            row["class16_ignored_acoustic_points"] += int(ignored[indexes].sum())
            selected = indexes[acoustic[indexes]]
            row["class13_nominal_200_300ft_navd88_points"] += int(((z[selected] <= -60.96) & (z[selected] >= -91.44)).sum())
            row["source_ids"].update(int(value) for value in source_ids[selected])
    rows = []
    for item in matrix["review_order"]:
        ident = item["context_id"]
        row = result[ident]
        rows.append({
            "context_id": ident,
            "historical_rockfish_positive_windows": item["historical_rockfish_positive_windows"],
            "prior_mapped_mpa_or_gea_review_hold": item["mapped_protected_area_or_gea_buffer"],
            "prior_enc_danger_review_hold": item["mapped_enc_danger_buffer"],
            "intersecting_tiles": memberships[ident],
            "tiles_with_any_points_in_outline": row["tile_names"],
            "class13_acoustic_points": row["class13_acoustic_points"],
            "class13_nominal_200_300ft_navd88_points": row["class13_nominal_200_300ft_navd88_points"],
            "class16_ignored_acoustic_points": row["class16_ignored_acoustic_points"],
            "class13_point_source_id_counts": {str(key): value for key, value in sorted(row["source_ids"].items())},
            "mllw_depth_qualified": False, "upper_vertical_error_qualified": False,
            "independent_survey_qualified": False, "fishing_target": False, "exportable": False,
        })
    camera = [r for r in rows if r["historical_rockfish_positive_windows"]]
    return {
        "schema_version": 1, "scope": "monterey-noaa-2013-merge-acoustic-point-support",
        "tile_index_url": BASE + INDEX, "tile_index_sha256": INDEX_SHA,
        "copc_tile_sha256": TILE_SHA, "copc_tile_urls": official_urls,
        "research_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "research_context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "point_horizontal_crs": "EPSG:3717", "point_vertical_crs": "EPSG:5703 NAVD88 height",
        "acoustic_class": 13, "ignored_acoustic_class": 16,
        "outlines_reviewed": len(rows), "tiles_reviewed": len(official_urls),
        "outlines_with_class13_points": sum(r["class13_acoustic_points"] > 0 for r in rows),
        "camera_positive_outlines_with_class13_points": sum(r["class13_acoustic_points"] > 0 for r in camera),
        "outlines_with_nominal_200_300ft_navd88_points": sum(r["class13_nominal_200_300ft_navd88_points"] > 0 for r in rows),
        "outlines": rows, "fishing_target": False, "exportable": False,
        "next_acquisition": "Map point_source_id to the NOAA 2013 Full_DataInventory and acoustic source extents; obtain source survey, vertical accuracy/TPU and MLLW transformation before cell-depth review. Recheck legal/ENC screens separately.",
        "limitations": [
            "Class 13 denotes submerged acoustic samples in the 2013 merged cloud; NOAA's processing report says some source BAG grid nodes were exported to ASCII and imported as points. These are not necessarily original sonar beams and do not prove survey independence, positional accuracy, seabed material or fish presence.",
            "The 2013 NOAA merged points and USGS 2016 2 m resample share lineage and cannot be treated as independent corroboration.",
            "The LAS gps_time field is uninitialized/inconsistent for sampled acoustic tiles; file names and tile-wide STAC dates are not per-point survey dates.",
            "Nominal NAVD88 elevations are not MLLW depths. No conservative upper error or chart-datum limit has been established.",
            "The outline is research context, not a navigable or fishable patch; no exact coordinates or point geometries are published.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research/receipts/monterey-noaa2612-acoustic-point-support.json"))
    args = parser.parse_args()
    report = build(args.root.resolve(), args.fetch)
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if report != {key: value for key, value in saved.items() if key != "checked_at"}:
            raise ValueError("NOAA COPC acoustic-point support changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Class-13 acoustic support: {report['outlines_with_class13_points']}/17 outlines; zero fishing targets")


if __name__ == "__main__":
    main()

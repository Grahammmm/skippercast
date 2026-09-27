#!/usr/bin/env python3
"""Audit NOAA CoNED source polygons across 17 Monterey research outlines."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely import wkb
from shapely.geometry import shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
URL = ("https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/"
       "CA_Central_CoNED_DEM_2017_8657/CentCA_Topobathy_DEM_Spatial_Metadata.gpkg")
SHA256 = "721c073303b60a09d479256b1ccb1d1e3b7088232f7a6a3f8837ef0fd3feb379"
TABLE = "CentCA_Topobathy_DEM_Spatial_Metadata_v3"
CONTEXT = ROOT / "dist/data/usgs-offshore-monterey-hard-context.geojson"
MATRIX = ROOT / "dist/data/monterey-original-300-paired-review.json"


def verified_source(path: Path, fetch: bool) -> None:
    if fetch:
        request = Request(URL, headers={"User-Agent": "SkipperCast-source-audit/1.0"})
        path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(request, timeout=120) as response, path.open("wb") as output:
            total = 0
            while chunk := response.read(1 << 20):
                total += len(chunk)
                if total > 121_000_000:
                    raise ValueError("NOAA spatial metadata package oversized")
                output.write(chunk)
    if not path.exists() or path.stat().st_size != 120_184_832:
        raise ValueError("NOAA spatial metadata package missing or changed")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != SHA256:
        raise ValueError("NOAA spatial metadata package changed")


def gpkg_polygon(blob):
    if not blob or blob[:4] != b"GP\x00\x01" or struct.unpack("<i", blob[4:8])[0] != 3717:
        raise ValueError("Unexpected GeoPackage geometry header or CRS")
    geometry = wkb.loads(blob[8:])
    if geometry.geom_type != "MultiPolygon" or geometry.is_empty:
        raise ValueError("NOAA source footprint geometry changed")
    return geometry


def build(source: Path, context_path: Path = CONTEXT, matrix_path: Path = MATRIX) -> dict:
    verified_source(source, fetch=False)
    matrix = json.loads(matrix_path.read_text())
    candidate_ids = {row["context_id"] for row in matrix["outlines"]}
    if len(candidate_ids) != 17 or matrix.get("fishing_target") is not False:
        raise ValueError("Original Monterey research matrix changed")
    project = Transformer.from_crs("EPSG:4326", "EPSG:3717", always_xy=True)
    context = json.loads(context_path.read_text())
    outlines = {}
    for feature in context["features"]:
        ident = feature["properties"].get("id", "")
        if ident in candidate_ids:
            if feature["properties"].get("fishing_target") is not False:
                raise ValueError("Original research outline changed")
            outlines[ident[-3:]] = transform(project.transform, shape(feature["geometry"]))
    if set(outlines) != {ident[-3:] for ident in candidate_ids}:
        raise ValueError("Original research outline set changed")
    connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    try:
        columns = connection.execute(f"PRAGMA table_info({TABLE})").fetchall()
        required = {"OBJECTID", "Shape", "Title", "Source_Project", "Date_Acquired",
                    "Data_Type", "Source_Resolution", "Source_Vertical_Datum", "Geoid",
                    "Source_Publication"}
        if not required.issubset({row[1] for row in columns}):
            raise ValueError("NOAA source-footprint schema changed")
        geometry_column = connection.execute("SELECT column_name, geometry_type_name, srs_id FROM gpkg_geometry_columns WHERE table_name=?", (TABLE,)).fetchone()
        if geometry_column != ("Shape", "MULTIPOLYGON", 3717):
            raise ValueError("NOAA source-footprint CRS changed")
        rows = connection.execute(f"SELECT OBJECTID, Title, Source_Project, Date_Acquired, Data_Type, Source_Resolution, Source_Vertical_Datum, Geoid, Source_Publication, Shape FROM {TABLE}").fetchall()
    finally:
        connection.close()
    if len(rows) != 67:
        raise ValueError("NOAA source-footprint row count changed")
    matches = {ident: [] for ident in outlines}
    for row in rows:
        geometry = gpkg_polygon(row[-1])
        for ident, outline in outlines.items():
            if not geometry.intersects(outline):
                continue
            fraction = geometry.intersection(outline).area / outline.area
            if fraction <= 0:
                continue
            matches[ident].append({
                "source_object_id": row[0], "title": row[1], "source_project": row[2],
                "date_acquired_label": row[3], "data_type": row[4],
                "source_resolution_label": row[5], "source_vertical_datum_label": row[6],
                "source_geoid_label": row[7], "source_publication": row[8],
                "outline_area_fraction": round(fraction, 4),
            })
    if ({row["source_object_id"] for group in matches.values() for row in group} != {6, 10, 29}
            or [row["source_object_id"] for row in matches["001"]] != [6, 10, 29]
            or [row["source_object_id"] for row in matches["023"]] != [10]
            or [row["source_object_id"] for row in matches["072"]] != [10]):
        raise ValueError("NOAA source lineage over research outlines changed")
    return {
        "schema_version": 1,
        "scope": "monterey-2017-coned-original-source-footprints-over-17-research-outlines",
        "source_url": URL, "source_sha256": SHA256,
        "research_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "source_footprints_checked": len(rows), "research_outlines_checked": len(outlines),
        "source_object_ids_intersecting_outlines": [6, 10, 29],
        "outlines": {ident: {
            "source_footprints": matches[ident],
            "independent_newer_measured_source_established": False,
            "source_cell_or_survey_lineage_verified": False,
            "fishing_target": False,
        } for ident in sorted(outlines)},
        "original_noaa_2013_merge_inventory_obtained": False,
        "cellwise_upper_uncertainty_obtained": False,
        "mllw_depth_qualified": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "These are 2017 CoNED compilation source polygons, not observed acoustic cells or an inventory of the 2013 merge's contributing surveys.",
            "The 2009 date label for 2013 merge polygons is not a date for every source sounding.",
            "Outline 001 intersects a void-fill source footprint; exact cell overlap and interpolation mask are not supplied by this vector source.",
            "No newer independent measured source footprint intersects these 17 research outlines in this release; the spatial metadata is not a complete catalog of all possible surveys.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "var/review/CentCA_Topobathy_DEM_Spatial_Metadata.gpkg")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/monterey-coned-source-footprint-audit.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    verified_source(args.source, args.fetch)
    result = build(args.source)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("CoNED source footprint relationship changed; hold for review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("CoNED source footprints audited across 17 Monterey outlines; no independent depth qualification")


if __name__ == "__main__":
    main()

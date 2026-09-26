#!/usr/bin/env python3
"""Screen private Point Buchon ROV research blocks against fresh official GIS.

This is a bounded MPA/GEA/ENC danger triage, not fishing or navigation clearance.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

from scripts.audit_monterey_300_closures import official_query_envelope, safe_union
from scripts.audit_point_buchon_original_pair import CLASS_NAMES, LOWER_M, UPPER_M, original_tiff
from scripts.build_central_rov_depth_evidence import source_bytes
from scripts.refresh_enc_hazards import LAYERS, SERVICES


ROOT = Path(__file__).resolve().parents[1]
GRID_M = 100
MARGIN_M = 100
EXPECTED_MPAS = {"Morro Bay SMRMA", "Point Buchon SMCA", "Point Buchon SMR"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feature_fingerprint(features):
    normalized = [json.dumps({"geometry": row["geometry"], "properties": row["properties"]},
                             sort_keys=True, separators=(",", ":")) for row in features]
    return hashlib.sha256("\n".join(sorted(normalized)).encode()).hexdigest()


def fresh(value, now):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or not 0 <= (now - instant).total_seconds() <= 36 * 3600:
        raise ValueError("Official Point Buchon source is stale or future dated")


def source_blocks(bathy_zip, character_zip, rov_csv, rov_pin):
    source_bytes(rov_csv, rov_pin)
    blocks = defaultdict(lambda: {"subunits": 0, "lingcod_seen": 0, "vermilion_seen": 0,
                                  "classes": Counter(), "years": set()})
    seen = set()
    with rasterio.open(original_tiff(bathy_zip)) as bathy, rasterio.open(original_tiff(character_zip)) as character:
        if (bathy.shape != character.shape or bathy.transform != character.transform
                or str(bathy.crs) != "EPSG:32610" or character.crs != bathy.crs):
            raise ValueError("Original Point Buchon survey grids changed")
        with rov_csv.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            required = {"LongTerm_Region", "MPAGroup", "Protection", "Type", "Avg.X", "Avg.Y",
                        "Avg.Depth", "SurveyYear", "X10m_ID", "Lingcod", "Vermilion_rf"}
            if not required.issubset(reader.fieldnames):
                raise ValueError("ROV source schema changed")
            for row in reader:
                if (row["LongTerm_Region"] != "Central" or row["MPAGroup"] != "Point Buchon"
                        or row["Protection"] != "0" or row["Type"] != "Reference"):
                    continue
                if not LOWER_M <= float(row["Avg.Depth"]) <= UPPER_M:
                    continue
                ident = row["X10m_ID"]
                if ident in seen:
                    raise ValueError("Duplicate Point Buchon ROV subunit")
                seen.add(ident)
                x, y = float(row["Avg.X"]) * 1000, float(row["Avg.Y"]) * 1000
                code = next(character.sample([(x, y)], masked=True))[0]
                depth = next(bathy.sample([(x, y)], masked=True))[0]
                if code is None or depth is None or np.ma.is_masked(code) or np.ma.is_masked(depth):
                    raise ValueError("Open-reference ROV center lacks paired original USGS cells")
                kind = CLASS_NAMES.get(int(code))
                if kind is None:
                    raise ValueError("Open-reference ROV center has unknown class")
                key = (int(x // GRID_M), int(y // GRID_M))
                item = blocks[key]
                item["subunits"] += 1
                item["lingcod_seen"] += int(row["Lingcod"])
                item["vermilion_seen"] += int(row["Vermilion_rf"])
                item["classes"][kind] += 1
                item["years"].add(int(row["SurveyYear"]))
    if len(seen) != 183 or sum(item["classes"]["hard_rugose"] for item in blocks.values()) != 58:
        raise ValueError("Original Point Buchon ROV open-reference research set changed")
    return blocks


def closures(mpas, federal, enc, now):
    if (mpas.get("status") != "research-closure-screen-only"
            or {row["properties"]["NAME"] for row in mpas.get("features", [])} != EXPECTED_MPAS
            or mpas.get("exceededTransferLimit")
            or federal.get("status") != "ok"
            or federal.get("scope") != "noaa-west-coast-groundfish-conservation-areas"
            or len(federal.get("source_layers", [])) < 25
            or federal.get("feature_count") != len(federal.get("features", []))
            or enc.get("scope_id") != "point-buchon-open-reference-hard-context"
            or enc.get("bounds") != [-121.02, 35.10, -120.79, 35.33]
            or enc.get("status") != "charted-danger-screen-only"
            or enc.get("source_url") != "https://encdirect.noaa.gov/arcgis/rest/services/encdirect"
            or {(row["service"], row["layer"]) for row in enc.get("query_receipts", [])}
            != {(service, layer) for service in SERVICES for layer in LAYERS}
            or sum(row["count"] for row in enc["query_receipts"]) != len(enc.get("features", []))):
        raise ValueError("Point Buchon official closure or ENC query set changed")
    for date in (mpas["checked_at"], federal["retrieved_at"], enc["checked_at"]):
        fresh(date, now)
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    cdfw_coverage = transform(project, official_query_envelope(mpas["source_url"]))
    enc_coverage = transform(project, box(*enc["bounds"]))
    mpa = safe_union(mpas["features"], project)
    geas = [row for row in federal["features"] if row["properties"]["area_type"] == "GEA"]
    if len(geas) < 10:
        raise ValueError("NOAA GEA source incomplete")
    gea = safe_union(geas, project)
    dangers = [transform(project, shape(row["geometry"])) for row in enc["features"]]
    if any(item.is_empty or not item.is_valid for item in dangers):
        raise ValueError("NOAA ENC danger geometry changed")
    return cdfw_coverage, enc_coverage, mpa, gea, unary_union(dangers), len(geas)


def build(blocks, mpas, federal, enc, *, now=None):
    now = now or datetime.now(timezone.utc)
    cdfw_coverage, enc_coverage, mpa, gea, danger, gea_count = closures(mpas, federal, enc, now)
    totals = Counter()
    private = []
    for (east, north), item in sorted(blocks.items()):
        footprint = box(east * GRID_M, north * GRID_M,
                        (east + 1) * GRID_M, (north + 1) * GRID_M)
        margin = footprint.buffer(MARGIN_M)
        if not cdfw_coverage.covers(margin) or not enc_coverage.covers(margin):
            raise ValueError("Official query does not cover full Point Buchon research margin")
        holds = {"mpa": margin.intersects(mpa), "gea": margin.intersects(gea),
                 "charted_danger": not danger.is_empty and margin.intersects(danger)}
        totals["blocks"] += 1
        totals["subunits"] += item["subunits"]
        totals["hard_rugose_subunits"] += item["classes"]["hard_rugose"]
        for label, held in holds.items():
            totals[label + "_margin_blocks"] += int(held)
            totals[label + "_margin_subunits"] += item["subunits"] if held else 0
        totals["all_three_clear_margin_blocks"] += int(not any(holds.values()))
        private.append({"type": "Feature", "geometry": mapping(footprint),
                        "properties": {"subunits": item["subunits"], "classes": dict(item["classes"]),
                                       "lingcod_seen": item["lingcod_seen"],
                                       "vermilion_seen": item["vermilion_seen"],
                                       "observation_years": sorted(item["years"]),
                                       "review_holds": holds, "fishing_target": False,
                                       "exportable": False}})
    return ({"schema_version": 1, "scope": "point-buchon-open-reference-rov-100m-access-triage",
             "grid_m": GRID_M, "review_margin_m": MARGIN_M,
             "cdfw_mpa_feature_count": len(mpas["features"]),
             "noaa_gea_feature_count": gea_count,
             "noaa_enc_danger_feature_count": len(enc["features"]),
             "noaa_enc_query_layers": len(enc["query_receipts"]),
             "source_checked_at": {"cdfw_mpa": mpas["checked_at"],
                                   "noaa_federal": federal["retrieved_at"],
                                   "noaa_enc": enc["checked_at"]},
             "source_urls": {"cdfw_mpa": mpas["source_url"],
                             "noaa_federal": federal["service_url"],
                             "noaa_enc": enc["source_url"]},
             "official_geometry_sha256": {
                 "cdfw_mpas": feature_fingerprint(mpas["features"]),
                 "noaa_federal_geas": feature_fingerprint(
                     [row for row in federal["features"] if row["properties"]["area_type"] == "GEA"]),
                 "noaa_enc_dangers": feature_fingerprint(enc["features"]),
             },
             "totals": dict(sorted(totals.items())), "qualified_waypoints": 0,
             "fishing_target": False, "exportable": False,
             "limitations": ["Historical 10 m ROV subunits are grouped into 100 m private research blocks, not fishable reef boundaries or current catch observations.",
                             "A 100 m GIS review margin is not an uncertainty-derived safe approach, drift or transit buffer.",
                             "CDFW MPA, NOAA GEA and three-scale ENC danger layers are a partial screen; other closures, security areas, current rules, chart completeness and full routes remain unresolved.",
                             "The original USGS 200–300 ft band is source-datum only and has no established upper depth uncertainty."]},
            {"type": "FeatureCollection", "crs": "EPSG:32610",
             "scope": "private-point-buchon-rov-100m-research-blocks", "features": private})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bathy", type=Path, default=ROOT / "var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon.zip")
    parser.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip")
    parser.add_argument("--rov", type=Path, default=ROOT / "var/review/rov-zenodo-10929417.csv")
    parser.add_argument("--mpas", type=Path, required=True)
    parser.add_argument("--federal", type=Path, required=True)
    parser.add_argument("--enc", type=Path, required=True)
    parser.add_argument("--private-blocks", type=Path, default=ROOT / "var/review/point-buchon-rov-100m-blocks.geojson")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-rov-access-triage.json")
    args = parser.parse_args()
    pin = json.loads((ROOT / "catalog/central-rov-2024-source.json").read_text())
    blocks = source_blocks(args.bathy, args.character, args.rov, pin)
    mpas, federal, enc = (json.loads(path.read_text()) for path in (args.mpas, args.federal, args.enc))
    report, private = build(blocks, mpas, federal, enc)
    report["input_sha256"] = {"bathy": sha256(args.bathy), "character": sha256(args.character),
                              "rov": sha256(args.rov), "mpas": sha256(args.mpas),
                              "federal": sha256(args.federal), "enc": sha256(args.enc)}
    args.private_blocks.parent.mkdir(parents=True, exist_ok=True)
    args.private_blocks.write_text(json.dumps(private, separators=(",", ":")) + "\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["totals"])


if __name__ == "__main__":
    main()

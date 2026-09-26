#!/usr/bin/env python3
"""Aggregate independent Estero depth/class overlap and screen research blocks.

The 100 m blocks are a review index, not rock footprints or fishing waypoints.
NAVD88 depth, frame registration, uncertainty, current rules, chart hazards and
biological evidence remain separate release gates.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

from scripts.audit_estero_2012_2008_overlap import original_character
from scripts.audit_usgs_estero_2012_original import ARCHIVES, ascii_member, header
from scripts.audit_point_estero_original_pair import PIN as ESTERO_2008_PIN
from scripts.audit_monterey_300_closures import official_query_envelope, safe_union
from scripts.refresh_enc_hazards import SERVICES as ENC_SERVICES, LAYERS as ENC_LAYERS

ROOT = Path(__file__).resolve().parents[1]
BANDS = ((200, 250), (250, 300))
GRID_M = 100
BUFFER_M = 100


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry_sha256(features):
    return hashlib.sha256(json.dumps(features, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def verify_closures(mpas, federal, now):
    expected = {"Morro Bay SMRMA", "Cambria SMCA", "White Rock SMCA",
                "Point Buchon SMCA", "Point Buchon SMR"}
    if ({f.get("properties", {}).get("NAME") for f in mpas.get("features", [])} != expected
            or mpas.get("exceededTransferLimit")
            or federal.get("status") != "ok"
            or federal.get("scope") != "noaa-west-coast-groundfish-conservation-areas"
            or len(federal.get("source_layers", [])) < 25
            or federal.get("feature_count") != len(federal.get("features", []))):
        raise ValueError("Official closure set is incomplete or changed")
    for value in (mpas.get("checked_at"), federal.get("retrieved_at")):
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or not 0 <= (now - instant).total_seconds() <= 36 * 3600:
            raise ValueError("Official closure source is stale or future dated")
    envelope = official_query_envelope(mpas["source_url"])
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    query_coverage = transform(project, envelope)
    mpa_union = safe_union(mpas["features"], project)
    geas = [f for f in federal["features"] if f["properties"]["area_type"] == "GEA"]
    if len(geas) < 10:
        raise ValueError("Federal GEA set is incomplete")
    gea_union = safe_union(geas, project)
    return query_coverage, mpa_union, gea_union, len(geas)


def verify_enc(enc, now):
    if (enc.get("scope_id") != "estero-independent-deep-hard-context"
            or enc.get("region_id") != "morro-bay"
            or enc.get("source_url") != "https://encdirect.noaa.gov/arcgis/rest/services/encdirect"
            or enc.get("status") != "charted-danger-screen-only"
            or len(enc.get("query_receipts", [])) != 18
            or {(row["service"], row["layer"]) for row in enc.get("query_receipts", [])}
            != {(service, layer) for service in ENC_SERVICES for layer in ENC_LAYERS}
            or sum(row["count"] for row in enc["query_receipts"]) != len(enc.get("features", []))
            or {row["service"] for row in enc["query_receipts"]}
            != {"enc_harbour", "enc_approach", "enc_coastal"}):
        raise ValueError("NOAA ENC danger queries are incomplete")
    instant = datetime.fromisoformat(enc["checked_at"].replace("Z", "+00:00"))
    if instant.tzinfo is None or not 0 <= (now - instant).total_seconds() <= 36 * 3600:
        raise ValueError("NOAA ENC danger queries are stale or future dated")
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    coverage = transform(project, box(*enc["bounds"]))
    dangers = [transform(project, shape(feature["geometry"])) for feature in enc["features"]]
    if any(geometry.is_empty or not geometry.is_valid for geometry in dangers):
        raise ValueError("Invalid NOAA ENC danger geometry")
    return coverage, unary_union(dangers)


def source_blocks(depth_zip, class_zip):
    if sha256(depth_zip) != ARCHIVES[depth_zip.name]:
        raise ValueError("Original 2012 depth archive changed")
    if sha256(class_zip) != ESTERO_2008_PIN[class_zip.name]:
        raise ValueError("Original 2008 character archive changed")
    archive, source = ascii_member(depth_zip)
    transformer = Transformer.from_crs("EPSG:26910", "EPSG:32610", always_xy=True)
    blocks = Counter()
    try:
        grid = header(source)
        if (grid["xllcorner"] != 665811.16966312
                or grid["yllcorner"] != 3900237.4867247
                or grid["cellsize"] != 2):
            raise ValueError("Original 2012 grid registration changed")
        ncol, nrow = int(grid["ncols"]), int(grid["nrows"])
        xs = grid["xllcorner"] + (np.arange(ncol) + .5) * 2
        with rasterio.open(original_character(class_zip)) as character:
            if (str(character.crs) != "EPSG:32610" or character.count != 1
                    or any(abs(x - 2) > .01 for x in character.res)):
                raise ValueError("Original 2008 class grid changed")
            classes = character.read(1)
            for row in range(nrow):
                line = np.fromstring(source.readline().decode("ascii"), sep=" ")
                if line.size != ncol:
                    raise ValueError(f"Truncated 2012 depth row {row}")
                y = grid["yllcorner"] + (nrow - row - .5) * 2
                if y < character.bounds.bottom - 5 or y > character.bounds.top + 5:
                    continue
                x2, y2 = transformer.transform(xs, np.full(ncol, y))
                cols = np.floor((x2 - character.bounds.left) / 2).astype("int32")
                rows = np.floor((character.bounds.top - y2) / 2).astype("int32")
                inside = ((cols >= 0) & (cols < character.width)
                          & (rows >= 0) & (rows < character.height))
                for lo, hi in BANDS:
                    band = (inside & (line != -9999)
                            & (-line >= lo / 3.280839895)
                            & (-line < hi / 3.280839895))
                    selected = np.where(band)[0]
                    if selected.size == 0:
                        continue
                    rugged = selected[classes[rows[selected], cols[selected]] == 3]
                    if rugged.size == 0:
                        continue
                    bins = np.column_stack((np.floor(x2[rugged] / GRID_M).astype("int32"),
                                            np.floor(y2[rugged] / GRID_M).astype("int32")))
                    unique, counts = np.unique(bins, axis=0, return_counts=True)
                    for (east, north), count in zip(unique, counts):
                        blocks[(lo, hi, int(east), int(north))] += int(count)
        return blocks
    finally:
        source.close()
        archive.close()


def screen(blocks, query_coverage, mpas, geas, enc_coverage, enc_dangers):
    by_band = {f"{lo}-{hi}ft": {"blocks": 0, "hard_rugose_cells": 0,
                                "within_mpa_review_margin_blocks": 0,
                                "within_gea_review_margin_blocks": 0,
                                "within_enc_danger_review_margin_blocks": 0,
                                "outside_both_review_margins_blocks": 0,
                                "outside_both_review_margins_cells": 0,
                                "outside_mpa_gea_enc_danger_margins_blocks": 0}
               for lo, hi in BANDS}
    features = []
    for (lo, hi, east, north), count in sorted(blocks.items()):
        footprint = box(east * GRID_M, north * GRID_M,
                        (east + 1) * GRID_M, (north + 1) * GRID_M)
        margin = footprint.buffer(BUFFER_M)
        if not query_coverage.covers(margin):
            raise ValueError("CDFW query does not cover a whole research review margin")
        if not enc_coverage.covers(margin):
            raise ValueError("NOAA ENC queries do not cover a whole research review margin")
        mpa_hold = margin.intersects(mpas)
        gea_hold = margin.intersects(geas)
        enc_hold = not enc_dangers.is_empty and margin.intersects(enc_dangers)
        row = by_band[f"{lo}-{hi}ft"]
        row["blocks"] += 1
        row["hard_rugose_cells"] += count
        row["within_mpa_review_margin_blocks"] += int(mpa_hold)
        row["within_gea_review_margin_blocks"] += int(gea_hold)
        row["within_enc_danger_review_margin_blocks"] += int(enc_hold)
        if not mpa_hold and not gea_hold:
            row["outside_both_review_margins_blocks"] += 1
            row["outside_both_review_margins_cells"] += count
        if not mpa_hold and not gea_hold and not enc_hold:
            row["outside_mpa_gea_enc_danger_margins_blocks"] += 1
        features.append({"type": "Feature", "geometry": mapping(footprint),
                         "properties": {"band": f"{lo}-{hi}ft", "hard_rugose_cells": count,
                                        "mpa_review_hold": mpa_hold, "gea_review_hold": gea_hold,
                                        "enc_danger_review_hold": enc_hold,
                                        "fishing_target": False, "exportable": False}})
    return by_band, {"type": "FeatureCollection", "crs": "EPSG:32610",
                     "scope": "private-estero-nominal-research-blocks", "features": features}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--depth", type=Path, default=ROOT / "var/review/estero-bay-2012/NAD83_utm10_EsteroBay.zip")
    p.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-estero/SeafloorCharacter_OffshorePointEstero.zip")
    p.add_argument("--mpas", type=Path, required=True)
    p.add_argument("--federal", type=Path, required=True)
    p.add_argument("--enc", type=Path, required=True)
    p.add_argument("--private-blocks", type=Path, default=ROOT / "var/review/estero-nominal-research-blocks.geojson")
    p.add_argument("--output", type=Path, default=ROOT / "dist/data/estero-2012-depth-class-closure-block-review.json")
    args = p.parse_args()
    now = datetime.now(timezone.utc)
    mpas = json.loads(args.mpas.read_text())
    federal = json.loads(args.federal.read_text())
    enc = json.loads(args.enc.read_text())
    query, mpa_union, gea_union, gea_count = verify_closures(mpas, federal, now)
    enc_coverage, enc_dangers = verify_enc(enc, now)
    blocks = source_blocks(args.depth, args.character)
    bands, private = screen(blocks, query, mpa_union, gea_union, enc_coverage, enc_dangers)
    if sum(row["hard_rugose_cells"] for row in bands.values()) != 24_210:
        raise ValueError("Nominal independent hard/rugose source count changed")
    private["limitations"] = "Research blocks include old classified cells, not verified rocks or lawful targets. Never publish this file as fishing waypoints."
    args.private_blocks.parent.mkdir(parents=True, exist_ok=True)
    args.private_blocks.write_text(json.dumps(private, separators=(",", ":")) + "\n")
    result = {"schema_version": 1, "scope": "estero-independent-research-block-closure-screen",
              "grid_m": GRID_M, "review_margin_m": BUFFER_M,
              "depth_datum": "NAVD88 Geoid12; nominal comparison only",
              "source_2012": "https://doi.org/10.3133/ofr20131225",
              "source_2008": "https://doi.org/10.5066/P9ZSTUK1",
              "cdfw_source_url": mpas["source_url"], "cdfw_feature_count": len(mpas["features"]),
              "cdfw_checked_at": mpas["checked_at"],
              "noaa_source_url": federal["service_url"], "noaa_gea_feature_count": gea_count,
              "noaa_federal_retrieved_at": federal["retrieved_at"],
              "noaa_enc_source_url": enc["source_url"], "noaa_enc_checked_at": enc["checked_at"],
              "noaa_enc_query_layers": len(enc["query_receipts"]),
              "noaa_enc_charted_danger_features": len(enc["features"]),
              "official_geometry_sha256": {
                  "cdfw_mpas": geometry_sha256(mpas["features"]),
                  "noaa_federal": geometry_sha256(federal["features"]),
                  "noaa_enc_dangers": geometry_sha256(enc["features"]),
              },
              "input_sha256": {"depth": sha256(args.depth), "character": sha256(args.character),
                               "cdfw": sha256(args.mpas), "federal": sha256(args.federal),
                               "enc": sha256(args.enc)},
              "bands": bands, "fishing_target": False, "exportable": False,
              "qualified_waypoints": 0,
              "limitations": ["100 m blocks aggregate nominal cells; a block is not the mapped reef footprint.",
                              "CDFW and NOAA GIS screening is conservative and approximate; exact law, notices, security areas, full ENC content and routes remain to review.",
                              "Zero returned NOAA ENC danger features in the 18 queried layers is not proof that the area is free of hazards.",
                              "Datum, registration, total depth uncertainty, biology, drift and safe transit gates remain open."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print({band: data["blocks"] for band, data in bands.items()})


if __name__ == "__main__":
    main()

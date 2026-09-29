"""Audit original NOAA/USGS hard-bottom context in a bounded regional preview.

This produces a research queue, never fishing marks, scores, routes or exports.
The original BAG, current MPA/GEA snapshots and all ENC danger layers must be
available and identity-checked before any historical outline is displayed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from skippercast.platform.bottom_targets import cells_qualified, terrain_metrics
from skippercast.platform.contracts import REPO, atomic_json


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fresh(value, now):
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None or not 0 <= (now - at).total_seconds() <= 36 * 3600:
        raise ValueError("Closure or chart research snapshot is stale")


def audit(region_id, enc_path, federal_path, *, root=REPO, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    region = json.loads((root / "regions" / region_id / "region.json").read_text())
    if region["id"] != region_id or region["status"] != "preview":
        raise ValueError("Expected a region-specific research preview")
    source_path = root / "dist/data/sf-native-hard-context.geojson"
    source_raw = source_path.read_bytes()
    source = json.loads(source_raw)
    if source.get("scope") != "sf-native-noaa-usgs-hard-bottom-context":
        raise ValueError("Expected reviewed original hard-bottom source context")
    enc_raw = Path(enc_path).read_bytes()
    enc = json.loads(enc_raw)
    scopes = json.loads((root / "catalog/noaa-enc-hazard-scopes.json").read_text())["scopes"]
    scope = next((s for s in scopes if s["id"] == enc.get("scope_id")), None)
    if (scope is None or scope.get("region_id") != region_id
            or enc.get("region_id") != region_id or enc.get("bounds") != scope["bounds"]
            or len(enc.get("query_receipts", [])) != 18
            or sum(x["count"] for x in enc["query_receipts"]) != len(enc.get("features", []))):
        raise ValueError("Incomplete or mismatched bounded NOAA ENC review")
    fresh(enc["checked_at"], now)
    federal_raw = Path(federal_path).read_bytes()
    federal = json.loads(federal_raw)
    if (federal.get("scope") != "noaa-west-coast-groundfish-conservation-areas"
            or federal.get("status") != "ok" or len(federal.get("features", [])) < 25):
        raise ValueError("Fresh complete NOAA federal exclusion snapshot required")
    fresh(federal["retrieved_at"], now)
    mpa_path = root / "dist" / region["assets"]["protected_areas"]
    mpa_raw = mpa_path.read_bytes()
    mpa = json.loads(mpa_raw)
    if (mpa.get("region_id") != region_id
            or len(mpa.get("features", [])) < region["mpa"]["minimum_features"]):
        raise ValueError("Wrong or incomplete regional CDFW MPA snapshot")
    fresh(mpa["checked_at"], now)
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    region_bounds = box(*region["fishing_bounds"])
    scope_bounds = box(*scope["bounds"])
    mpa_union = unary_union([transform(project, shape(f["geometry"])) for f in mpa["features"]]).buffer(100)
    geas = [f for f in federal["features"] if f["properties"].get("area_type") == "GEA"]
    if len(geas) < 10:
        raise ValueError("NOAA groundfish exclusion set is incomplete")
    gea_union = unary_union([transform(project, shape(f["geometry"])) for f in geas]).buffer(100)
    hazards = [transform(project, shape(f["geometry"])) for f in enc["features"]]
    if not hazards:
        raise ValueError("Empty chart danger screen needs manual review")
    hazard_tree = STRtree(hazards)
    candidates = []
    for feature in source["features"]:
        geom = shape(feature["geometry"])
        if geom.is_empty or not geom.intersects(region_bounds):
            continue
        p = feature["properties"]
        if (not region_bounds.covers(geom) or not scope_bounds.covers(geom)
                or p.get("fishing_target") is not False or p.get("exportable") is not False
                or p.get("native_resolution_m") != [2.0, 2.0]):
            raise ValueError("Research context escapes its exact region or source policy")
        candidates.append((p, geom))
    if not candidates:
        raise ValueError("No bounded source context for region")
    expected = {p["noaa_bag_sha256"] for p, _ in candidates}
    cache = {}
    for path in sorted((root / "var/noaa-native-cache").glob("*.bag")):
        value = digest(path)
        if value in expected:
            if value in cache:
                raise ValueError("Duplicate original NOAA BAG identity")
            cache[value] = path
    if set(cache) != expected:
        raise ValueError("One or more exact original NOAA BAG grids are unavailable")
    rows = []
    for p, geographic in candidates:
        projected = transform(project, geographic)
        near_danger = any(projected.distance(hazards[int(i)]) <= 100
                          for i in hazard_tree.query(projected.buffer(100)))
        hold = ("held-current-mpa" if projected.intersects(mpa_union) else
                "held-federal-gea" if projected.intersects(gea_union) else
                "held-charted-danger-proximity" if near_danger else None)
        with rasterio.open(cache[p["noaa_bag_sha256"]]) as ds:
            crs = CRS.from_wkt(ds.crs.to_wkt())
            parts = crs.sub_crs_list
            if (ds.driver != "BAG" or ds.count != 2 or ds.res != (2.0, 2.0)
                    or len(parts) != 2 or parts[1].to_epsg() != 5866
                    or "utm zone 10" not in parts[0].name.lower()):
                raise ValueError("Original BAG resolution, MLLW datum or bands changed")
            local = transform(Transformer.from_crs("EPSG:4326", parts[0], always_xy=True).transform, geographic)
            window = from_bounds(*local.bounds, transform=ds.transform).round_offsets().round_lengths()
            area_m2 = local.area
            if window.width < 1 or window.height < 1:
                inside = np.zeros((0, 0), dtype=bool)
                qualified = inside
                hold = hold or "held-subcell-display"
            else:
                depth = ds.read(1, window=window)
                uncertainty = ds.read(2, window=window)
                affine = ds.window_transform(window)
                inside = geometry_mask([local], out_shape=depth.shape, transform=affine, invert=True)
                qualified = cells_qualified(depth, uncertainty, 2) & inside
                if not inside.any():
                    hold = hold or "held-subcell-display"
            if hold is None and area_m2 < 2500:
                hold = hold or "held-small-display"
            elif hold is None and (qualified.sum() < 20 or not qualified.all(where=inside)):
                hold = hold or "held-native-cell-gap"
            terrain = None
            depth_stats = None
            if hold is None:
                yy, xx = np.where(qualified)
                east = affine.c + (xx + .5) * affine.a
                north = affine.f + (yy + .5) * affine.e
                terrain = terrain_metrics(east, north, depth[qualified], np.full(len(east), 2.0),
                                          hard_area_m2=area_m2)
                sampled = -depth[qualified].astype("float64") / .3048
                if not np.isfinite(sampled).all() or np.any((sampled < 25) | (sampled > 200)):
                    raise ValueError("Original depth escaped reviewed planning band")
                depth_stats = {"minimum": round(float(sampled.min()), 1),
                               "p05": round(float(np.percentile(sampled, 5)), 1),
                               "median": round(float(np.median(sampled)), 1),
                               "p95": round(float(np.percentile(sampled, 95)), 1),
                               "maximum": round(float(sampled.max()), 1)}
        rows.append({"context_id": p["id"], "survey_id": p["survey_id"],
                     "original_bag_sha256": p["noaa_bag_sha256"],
                     "display_area_m2": round(area_m2),
                     "native_cells_inside_display": int(inside.sum()),
                     "qualified_native_cells": int(qualified.sum()),
                     "near_selected_charted_danger": near_danger,
                     "status": hold or "terrain-reviewed", "terrain": terrain,
                     "sampled_original_depth_ft": depth_stats})
    rows.sort(key=lambda x: (x["terrain"]["habitat_score"] if x["terrain"] else -1,
                             x["display_area_m2"]), reverse=True)
    return {"schema_version": 1, "scope": "regional-original-native-hard-terrain-research-queue",
            "region_id": region_id, "audited_at": now.isoformat(),
            "source_context_sha256": hashlib.sha256(source_raw).hexdigest(),
            "enc_sha256": hashlib.sha256(enc_raw).hexdigest(),
            "mpa_sha256": hashlib.sha256(mpa_raw).hexdigest(),
            "federal_sha256": hashlib.sha256(federal_raw).hexdigest(),
            "reviewed_outlines": len(rows), "terrain_reviewed": sum(x["status"] == "terrain-reviewed" for x in rows),
            "holds": {reason: sum(x["status"] == reason for x in rows)
                      for reason in sorted({x["status"] for x in rows if x["status"] != "terrain-reviewed"})},
            "rows": rows, "status": "research-ranking-only",
            "limitations": "Original-cell terrain and depth describe dated historical seabed context only. ENC Direct is not navigation clearance; these outlines are not fish observations, fishing scores, routes, drifts or exports. Exact current chart, legal date/method, approach and species evidence remain unreviewed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--enc", type=Path, required=True)
    parser.add_argument("--federal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.region, args.enc, args.federal)
    atomic_json(args.output, result)
    print(json.dumps({"reviewed": result["reviewed_outlines"],
                      "terrain_reviewed": result["terrain_reviewed"], "holds": result["holds"]}))


if __name__ == "__main__":
    main()

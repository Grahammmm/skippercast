"""Measure original 1–2 m MLLW BAG terrain inside regular-grid research outlines.

This physical-habitat comparison has no catch calibration or fishing clearance.
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
from shapely.geometry import shape
from shapely.ops import transform

from skippercast.platform.bottom_targets import cells_qualified, terrain_metrics
from skippercast.platform.contracts import atomic_json


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fresh(value: str, now: datetime) -> None:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or not 0 <= (now - instant).total_seconds() <= 36 * 3600:
        raise ValueError("Site screen is stale")


def audit(queue, context, closures, bag_cache: Path, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (queue.get("scope") != "original-habitat-site-review-queue"
            or queue.get("fishing_target") is not False
            or closures.get("scope") != "original-habitat-shortlist-fresh-closure-audit"
            or closures.get("fishing_target") is not False
            or closures.get("shortlist_count") != queue.get("research_shortlist_count")
            or closures.get("held_count") != 0):
        raise ValueError("Unreviewed shortlist or closure screen")
    fresh(queue["enc_checked_at"], now)
    fresh(closures["cdfw_retrieved_at"], now)
    fresh(closures["noaa_retrieved_at"], now)
    features = {f["properties"]["id"]: f for f in context["features"]}
    rows = queue["research_shortlist"]
    closure_ids = {r["context_id"] for r in closures["outlines"]}
    if len(rows) != len(closure_ids) or closure_ids != {r["context_id"] for r in rows}:
        raise ValueError("Incomplete exact-outline closure join")
    expected = {features[r["context_id"]]["properties"]["noaa_bag_sha256"] for r in rows}
    bag_paths = {}
    for path in sorted(bag_cache.glob("H*.bag")):
        # Hash only plausible survey files; the full cache can hold many surveys.
        if not any(path.name.startswith(r["survey_id"] + "-") for r in rows):
            continue
        value = digest(path)
        if value in expected:
            if value in bag_paths:
                raise ValueError("Duplicate original BAG identity")
            bag_paths[value] = path
    if set(bag_paths) != expected:
        raise ValueError("Exact original BAG files missing or changed")
    metrics = []
    for item in rows:
        p = features[item["context_id"]]["properties"]
        if (p["survey_id"] != item["survey_id"] or p.get("fishing_target") is not False
                or p.get("exportable") is not False
                or p.get("native_resolution_m") not in ([1.0, 1.0], [2.0, 2.0])
                or item.get("charted_danger_within_review_buffer") is not False):
            raise ValueError("Original research geometry or chart gate changed")
        with rasterio.open(bag_paths[p["noaa_bag_sha256"]]) as ds:
            crs = CRS.from_wkt(ds.crs.to_wkt())
            parts = crs.sub_crs_list
            resolution = float(p["native_resolution_m"][0])
            if (ds.driver != "BAG" or ds.count != 2 or ds.res != (resolution, resolution)
                    or len(parts) != 2 or parts[1].to_epsg() != 5866
                    or "utm zone 10" not in parts[0].name.lower()):
                raise ValueError("Original BAG resolution or MLLW datum changed")
            polygon = transform(Transformer.from_crs("EPSG:4326", parts[0],
                                                      always_xy=True).transform,
                                shape(features[item["context_id"]]["geometry"]))
            if polygon.is_empty or not polygon.is_valid:
                raise ValueError("Invalid display outline")
            window = from_bounds(*polygon.bounds, transform=ds.transform).round_offsets().round_lengths()
            depth = ds.read(1, window=window)
            uncertainty = ds.read(2, window=window)
            affine = ds.window_transform(window)
            inside = geometry_mask([polygon], out_shape=depth.shape,
                                   transform=affine, invert=True)
            qualified = cells_qualified(depth, uncertainty, resolution) & inside
            if inside.sum() < 20 or not qualified.all(where=inside):
                metrics.append({"context_id": item["context_id"], "status": "held-native-cell-gap",
                                "native_cells_inside": int(inside.sum()),
                                "qualified_native_cells": int(qualified.sum()),
                                "terrain": None, "fishing_target": False, "exportable": False})
                continue
            yy, xx = np.where(qualified)
            east = affine.c + (xx + .5) * affine.a
            north = affine.f + (yy + .5) * affine.e
            local_hard_area = polygon.intersection(polygon.centroid.buffer(250)).area
            terrain = terrain_metrics(east, north, depth[qualified],
                                      np.full(len(east), resolution), hard_area_m2=local_hard_area)
            sampled = -depth[qualified].astype("float64") / .3048
            if not np.isfinite(sampled).all() or np.any((sampled < 25) | (sampled > 200)):
                raise ValueError("Original depth escaped reviewed 25–200 ft band")
            metrics.append({"context_id": item["context_id"], "status": "terrain-reviewed",
                            "survey_id": item["survey_id"], "display_area_m2": round(polygon.area),
                            "hard_area_within_250m_of_display_centroid_m2": round(local_hard_area),
                            "original_bag_sha256": p["noaa_bag_sha256"],
                            "native_cells_inside": int(inside.sum()),
                            "qualified_native_cells": int(qualified.sum()),
                            "sampled_original_depth_ft": {"minimum": round(float(sampled.min()), 1),
                                                           "median": round(float(np.median(sampled)), 1),
                                                           "maximum": round(float(sampled.max()), 1)},
                            "terrain": terrain, "fishing_target": False, "exportable": False})
    metrics.sort(key=lambda row: (row["terrain"]["habitat_score"] if row["terrain"] else -1,
                                  row.get("display_area_m2", 0)), reverse=True)
    return {"schema_version": 1, "scope": "original-regular-bag-shortlist-terrain-review",
            "profile_id": queue["profile_id"], "reviewed_at": now.isoformat(timespec="seconds"),
            "outline_count": len(metrics),
            "grades": {grade: sum(row["terrain"] is not None and
                                  row["terrain"]["habitat_grade"] == grade for row in metrics)
                       for grade in ("A", "B", "C")},
            "held_native_cell_gap": sum(row["status"] == "held-native-cell-gap" for row in metrics),
            "rows": metrics, "fishing_target": False, "exportable": False,
            "limitations": "Historical measured terrain score is not calibrated to fish abundance or catches. A sampled display polygon cannot establish exact boulder sizes, present bottom, safe navigation, route, local legal permission or good conditions."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue", required=True, type=Path)
    p.add_argument("--context", required=True, type=Path)
    p.add_argument("--closures", required=True, type=Path)
    p.add_argument("--bag-cache", type=Path, default=Path("var/noaa-native-cache"))
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    paths = {"queue": args.queue, "context": args.context, "closures": args.closures}
    data = audit(*(json.loads(path.read_text()) for path in paths.values()), args.bag_cache)
    data["input_sha256"] = {key: digest(path) for key, path in paths.items()}
    atomic_json(args.output, data)
    print(json.dumps({"reviewed": data["outline_count"], "grades": data["grades"],
                      "held_native_cell_gap": data["held_native_cell_gap"]}))


if __name__ == "__main__":
    main()

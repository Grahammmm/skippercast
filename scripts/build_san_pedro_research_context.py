"""Polygonize audited original USGS DS 552 rock cells for private closure review.

The resulting outlines and queue are historical research artifacts, never
public fishing spots, routes, bottom views or exports.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyproj import Transformer
import rasterio
from rasterio.features import shapes
from scipy.ndimage import find_objects, label
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from scripts.audit_usgs_ds552_san_pedro import SOURCES, archive_member, sha256, validate_raster
from skippercast.platform.contracts import atomic_json


SCOPE = "usgs-ds552-san-pedro-rock-context"
SURVEY = "USGS-DS552-2004"


def compile_context(audit: dict, cache: Path) -> tuple[dict, dict]:
    archive = cache / SOURCES["inner"][0]
    if (audit.get("scope") != "usgs-ds552-san-pedro-original-rock-camera-review"
            or audit.get("fishing_target") is not False
            or audit.get("exportable") is not False
            or audit.get("source_archives", {}).get("inner", {}).get("sha256") != sha256(archive)
            or audit.get("original_depth_review", {}).get("whole_footprint_depth_band_supported_components")
                != len(audit.get("inner_rock_review_queue", []))):
        raise ValueError("Original San Pedro source or full-footprint depth audit changed")
    rows = audit["inner_rock_review_queue"]
    if len(rows) != 24 or len({row["component_id"] for row in rows}) != len(rows):
        raise ValueError("Unreviewed San Pedro component count or identity")
    with rasterio.io.MemoryFile(archive_member(archive, ".tif")) as memory, memory.open() as ds:
        pixels = validate_raster(ds, 4)
        components, _ = label(pixels == 1)
        windows = find_objects(components)
        to_wgs = Transformer.from_crs(ds.crs, 4326, always_xy=True).transform
        features, queue = [], []
        for row in rows:
            ident = row["component_id"]
            review = row.get("original_full_rock_depth_review", {})
            if (row.get("fishing_target") is not False or row.get("exportable") is not False
                    or review.get("whole_footprint_depth_band_supported") is not True):
                raise ValueError("An unreviewed rock component escaped the research hold")
            window = windows[ident - 1]
            native = components[window] == ident
            cell_count = int(native.sum())
            if cell_count * 16 != row["rock_class_area_m2"] or cell_count != review["rock_cells"]:
                raise ValueError("Original component area or depth join changed")
            affine = ds.window_transform(((window[0].start, window[0].stop),
                                           (window[1].start, window[1].stop)))
            parts = [shape(geometry) for geometry, value in shapes(
                native.astype("uint8"), mask=native, transform=affine) if value == 1]
            if not parts:
                raise ValueError("Original component polygonization was empty")
            polygon = unary_union(parts)
            if not polygon.is_valid or abs(polygon.area - row["rock_class_area_m2"]) > .01:
                raise ValueError("Original raster polygon area changed")
            geometry = transform(to_wgs, polygon)
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError("Invalid transformed original rock outline")
            context_id = f"usgs-ds552-rock-{ident}"
            features.append({"type": "Feature", "geometry": mapping(geometry),
                             "properties": {"id": context_id, "survey_id": SURVEY,
                                            "component_id": ident, "native_rock_cells": cell_count,
                                            "fishing_target": False, "exportable": False}})
            queue.append({"context_id": context_id, "survey_id": SURVEY,
                          "component_id": ident, "fishing_target": False, "exportable": False})
    context = {"type": "FeatureCollection", "schema_version": 1, "scope": SCOPE,
               "source_archive_sha256": sha256(archive), "fishing_target": False,
               "exportable": False, "features": features}
    shortlist = {"schema_version": 1, "scope": "original-habitat-site-review-queue",
                 "source_context_outlines": len(features), "research_shortlist_count": len(queue),
                 "research_shortlist": queue, "fishing_target": False, "exportable": False,
                 "limitations": "Original 4 m 2004 rock-class research outlines; no current fish, chart, rules or access clearance."}
    return context, shortlist


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("var/review/usgs-ds552"))
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    args = parser.parse_args()
    context, queue = compile_context(json.loads(args.audit.read_text()), args.cache)
    atomic_json(args.context, context)
    atomic_json(args.queue, queue)
    print(json.dumps({"research_outlines": len(context["features"]), "fishing_targets": 0}))


if __name__ == "__main__":
    main()

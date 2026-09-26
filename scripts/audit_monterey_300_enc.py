#!/usr/bin/env python3
"""Compare Monterey research outlines with a fresh bounded NOAA ENC danger feed."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from scripts.audit_monterey_300_closures import fresh


def screen(footprint, hazards, tree, buffer_m=100):
    nearby = [int(i) for i in tree.query(footprint.buffer(buffer_m))
              if footprint.distance(hazards[int(i)]) <= buffer_m]
    nearest = int(tree.nearest(footprint))
    return {"nearest_charted_danger_in_scope_m": round(footprint.distance(hazards[nearest]), 1),
            "charted_dangers_within_100m": len(nearby),
            "within_charted_danger_review_buffer": bool(nearby)}


def audit(enc, pixel, context, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (enc.get("scope_id") != "monterey-original-300-hard-context"
            or len(enc.get("query_receipts", [])) != 18
            or sum(row["count"] for row in enc["query_receipts"]) != len(enc.get("features", []))
            or len(enc["features"]) < 1
            or pixel.get("scope") != "monterey-original-pixel-depth-band-audit"
            or pixel.get("fishing_target") is not False):
        raise ValueError("Incomplete original research or ENC danger source")
    fresh(enc["checked_at"], now)
    wgs_bounds = box(*enc["bounds"])
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    hazards = [transform(project, shape(row["geometry"])) for row in enc["features"]]
    if any(h.is_empty or not h.is_valid for h in hazards):
        raise ValueError("Invalid ENC danger geometry")
    tree = STRtree(hazards)
    features = {feature["properties"]["id"]: feature for feature in context["features"]}
    rows = []
    for item in pixel["outlines"]:
        feature = features.get(item["context_id"])
        if not feature or feature["properties"].get("fishing_target") is not False:
            raise ValueError("Original Monterey research outline changed")
        footprint_wgs = shape(feature["geometry"])
        if not wgs_bounds.contains(footprint_wgs):
            raise ValueError("ENC query bounds do not cover a full candidate outline")
        result = screen(transform(project, footprint_wgs), hazards, tree)
        rows.append({"context_id": item["context_id"], **result,
                     "fishing_target": False, "exportable": False})
    return {"schema_version": 1, "scope": "monterey-original-300-enc-danger-screen",
            "audited_at": now.isoformat(), "enc_checked_at": enc["checked_at"],
            "enc_source_url": enc["source_url"], "enc_scope_id": enc["scope_id"],
            "query_layer_count": 18, "charted_danger_features_in_scope": len(hazards),
            "outline_count": len(rows),
            "outlines_within_100m_of_charted_danger": sum(r["within_charted_danger_review_buffer"] for r in rows),
            "outlines": rows, "fishing_target": False, "exportable": False,
            "limitations": "ENC Direct feature proximity is only a research screen. It is not a navigation chart, chart-completeness finding, safe route, current maritime notice check or fishing permission."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enc", type=Path, required=True)
    parser.add_argument("--pixel", type=Path, default=Path("dist/data/monterey-original-300-pixel-review.json"))
    parser.add_argument("--context", type=Path, default=Path("dist/data/usgs-offshore-monterey-hard-context.geojson"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = {"enc": args.enc, "pixel": args.pixel, "context": args.context}
    loaded = {key: json.loads(path.read_text()) for key, path in inputs.items()}
    result = audit(loaded["enc"], loaded["pixel"], loaded["context"])
    result["input_sha256"] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in inputs.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['outlines_within_100m_of_charted_danger']}/{result['outline_count']} outlines near selected ENC dangers; zero fishing targets")


if __name__ == "__main__":
    main()

"""Publish original-cell terrain-reviewed outlines as research-only map context.

The audit, source context, official MPA/GEA snapshots and bounded ENC review
must match by digest. No outline from this builder is a fishing target or export.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from shapely.geometry import box, shape

from skippercast.platform.contracts import REPO, atomic_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(region_id, audit_path, enc_path, federal_path, *, root=REPO):
    root = Path(root)
    region = json.loads((root / "regions" / region_id / "region.json").read_text())
    audit = json.loads(Path(audit_path).read_text())
    source_path = root / "dist/data/sf-native-hard-context.geojson"
    source = json.loads(source_path.read_text())
    mpa_path = root / "dist" / region["assets"]["protected_areas"]
    if (region["id"] != region_id or region["status"] != "preview"
            or audit.get("scope") != "regional-original-native-hard-terrain-research-queue"
            or audit.get("region_id") != region_id or audit.get("status") != "research-ranking-only"
            or audit.get("source_context_sha256") != sha(source_path)
            or audit.get("mpa_sha256") != sha(mpa_path)
            or audit.get("federal_sha256") != sha(federal_path)
            or audit.get("enc_sha256") != sha(enc_path)
            or len(audit["rows"]) != audit["reviewed_outlines"]):
        raise ValueError("Regional original-cell context review changed or is incomplete")
    stamp = datetime.fromisoformat(audit["audited_at"])
    if stamp.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 36 * 3600:
        raise ValueError("Regional terrain research review is stale")
    rows = {r["context_id"]: r for r in audit["rows"]}
    if len(rows) != audit["reviewed_outlines"]:
        raise ValueError("Duplicate context identities")
    bounds = box(*region["fishing_bounds"])
    features = []
    for feature in source["features"]:
        p = feature["properties"]
        row = rows.get(p["id"])
        if row is None or row["status"] != "terrain-reviewed":
            continue
        geom = shape(feature["geometry"])
        depth = row["sampled_original_depth_ft"]
        if (not geom.is_valid or not bounds.covers(geom)
                or row["near_selected_charted_danger"] is not False
                or p["noaa_bag_sha256"] != row["original_bag_sha256"]
                or p["survey_id"] != row["survey_id"]
                or p["fishing_target"] is not False or p["exportable"] is not False
                or row["qualified_native_cells"] < 20
                or not 25 <= depth["minimum"] <= depth["p05"] <= depth["median"] <= depth["p95"] <= depth["maximum"] <= 200):
            raise ValueError("Research outline lacks exact original-cell proof")
        point = geom.representative_point()
        features.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
            "id": p["id"], "name": f"Fort Ross–Salt Point · historic hard-bottom outline {len(features)+1:02d}",
            "habitat_kind": "rock", "species_ids": ["reef"],
            "latitude": round(point.y, 7), "longitude": round(point.x, 7),
            "bounds": [round(v, 7) for v in geom.bounds],
            "area_km2": round(row["display_area_m2"] / 1_000_000, 5),
            "source_id": f"noaa-{p['survey_id'].lower()}-usgs-hard-class",
            "source_url": p["usgs_metadata_urls"][0],
            "source_links": [{"title": "Original NOAA depth grid", "url": p["noaa_bag_url"]},
                             {"title": "NOAA survey report", "url": p["survey_report_url"]}],
            "source_date": p["survey_dates"][0][:4],
            "survey_cell_m": max(p["native_resolution_m"]),
            "vertical_datum": "NOAA original BAG depth below MLLW",
            "depth_screened": True, "depth_qualified": False,
            "sampled_original_depth_ft": depth,
            "depth_note": "Measured 25–200 ft original cells inside an inset historic outline; this is neither continuous safe water nor a current chart depth.",
            "view_relief_m": row["terrain"]["relief_90_percent_m"],
            "qualified_original_cells": row["qualified_native_cells"],
            "limitations": "2007 historical NOAA/USGS research context. No calibrated catch rank, verified fish, current chart/route, harbor or exact date/method clearance. The bounded ENC danger screen is not navigation clearance.",
            "evidence_kind": "original-grid-and-usgs-class-historical-context",
            "catch_evidence": False, "charter_evidence": False, "quality_grade": None,
            "fishing_target": False, "fishing_export": False, "bottom_view": False,
        }})
    if len(features) != audit["terrain_reviewed"]:
        raise ValueError("Not all terrain-reviewed outlines were published")
    return {"type": "FeatureCollection", "schema_version": 1, "region_id": region_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_context_sha256": audit["source_context_sha256"],
            "terrain_reviewed_at": audit["audited_at"],
            "transformation_version": "regional-native-hard-to-preview-v1",
            "features": features,
            "summary": {"historical_research_outlines": len(features), "fishing_targets": 0},
            "source": {"attribution": "NOAA original MLLW BAG and USGS seafloor-character class",
                       "limitations": "Historical research context only; no fish, chart-route or legal clearance."}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--enc", type=Path, required=True)
    parser.add_argument("--federal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.region, args.audit, args.enc, args.federal)
    atomic_json(args.output, result)
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Screen private original 4 m research components against fresh official GIS.

Only aggregate distances and hold states are emitted. This is not legal,
security, route or navigation clearance and cannot publish fishing marks.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import reproject, Resampling
from scipy.ndimage import binary_erosion, label
from pyproj import Transformer
from shapely.geometry import Polygon, box, shape
from shapely.ops import transform, unary_union

from scripts.audit_monterey_300_closures import safe_union
from scripts.audit_point_conception_4m_hard_overlap import (
    MINIMUM_PATCH_M2, USGS_CACHE, USGS_SOURCE, source_tif,
)
from scripts.audit_point_conception_original_300_gap import CACHE, ROOT, file_sha256
from scripts.audit_point_conception_original_300_ladder import SOURCE_HASHES


OUTPUT = ROOT / "dist/data/point-conception-original-4m-access-screen.json"
VANDENBERG_ZONE_7_RULE = "https://www.ecfr.gov/current/title-33/chapter-II/part-334/section-334.1130"
VANDENBERG_LIVE_NOTICE = "https://www.vandenberg.spaceforce.mil/About-Us/Environmental/Vandenberg-SFB-Maritime-Updates/"


def vandenberg_zone_7():
    """Reviewed 33 CFR 334.1130(a)(2)(vii) perimeter; shoreline edge is approximate."""
    def dms(degrees, minutes, seconds):
        return degrees + minutes / 60 + seconds / 3600
    return Polygon([
        (-dms(120, 30, 10), dms(34, 30, 40)),
        (-dms(120, 37, 29), dms(34, 30, 40)),
        (-dms(120, 33, 6), dms(34, 26, 56)),
        (-dms(120, 28, 10), dms(34, 26, 56)),
    ])


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feature_digest(features):
    return hashlib.sha256(json.dumps(features, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fresh(value, *, hours=36):
    checked = datetime.fromisoformat(value.replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - checked).total_seconds()
    if checked.tzinfo is None or not 0 <= age <= hours * 3600:
        raise ValueError("Official GIS read is stale or future-dated")


def candidate_footprints(bag_cache, usgs_cache, prior):
    name, _, expected = USGS_SOURCE
    archive = usgs_cache / name
    if file_sha256(archive) != expected:
        raise ValueError("Original USGS character archive changed")
    candidates = []
    with rasterio.open(source_tif(archive)) as source:
        read = source.read(1, masked=True)
        character = np.where(np.ma.getmaskarray(read), 0, read.data).astype("uint8")
        for survey_id, files in SOURCE_HASHES.items():
            bag_name, bag_sha = next((item for item in files if "_4m_" in item[0]))
            bag_path = bag_cache / bag_name
            if file_sha256(bag_path) != bag_sha:
                raise ValueError("Original 4 m BAG changed")
            with rasterio.open(bag_path) as bag:
                e, u = bag.read(1), bag.read(2)
                placed = np.zeros(e.shape, dtype="uint8")
                reproject(character, placed, src_transform=source.transform,
                          src_crs=source.crs, src_nodata=0, dst_transform=bag.transform,
                          dst_crs="EPSG:26910", dst_nodata=0, resampling=Resampling.nearest)
                valid = (np.isfinite(e) & np.isfinite(u) & (e < 0) & (u > 0) & (u <= 1)
                         & (-e >= 60.96) & (-e + u + 2 <= 91.44))
                eligible = valid & binary_erosion(placed % 10 == 3, iterations=2, border_value=0)
                labels, _ = label(eligible)
                sizes = np.bincount(labels.ravel())
                retained = [int(i) for i in np.where(sizes * 16 >= MINIMUM_PATCH_M2)[0] if i]
                previous = next(row for row in prior["rows"] if row["survey_id"] == survey_id)
                if (len(retained) != previous["inset_components_at_least_2500m2"]
                        or int(sizes[1:].max() * 16) != previous["largest_inset_component_m2"]):
                    raise ValueError("Original 4 m research components changed")
                for component in retained:
                    mask = labels == component
                    pieces = [shape(geom) for geom, value in shapes(
                        mask.astype("uint8"), mask=mask, transform=bag.transform) if value]
                    footprint = unary_union(pieces)
                    if footprint.is_empty or not footprint.is_valid or int(footprint.area) != int(sizes[component] * 16):
                        raise ValueError("Original-cell component polygon changed")
                    candidates.append((survey_id, int(sizes[component]), footprint))
    if len(candidates) != prior["total_inset_components_at_least_2500m2"]:
        raise ValueError("Original 4 m component count changed")
    return candidates


def audit(prior, mpa_read, federal, enc, candidates):
    if (prior.get("scope") != "point-conception-original-4m-mllw-usgs-class3-aggregate-overlap"
            or prior.get("fishing_target") is not False
            or mpa_read.get("status") != "ok"
            or federal.get("scope") != "noaa-west-coast-groundfish-conservation-areas"
            or federal.get("status") != "ok"
            or enc.get("scope_id") != "point-conception-hard-context"):
        raise ValueError("Wrong research or official GIS source scope")
    fresh(mpa_read["checked_at"])
    fresh(federal["retrieved_at"])
    fresh(enc["checked_at"])
    mpa = mpa_read["data"]
    mpa_features = mpa["geojson"]["features"]
    geas = [f for f in federal["features"] if f["properties"]["area_type"] == "GEA"]
    if (mpa["feature_count"] != len(mpa_features) or len(mpa_features) < 150
            or len(geas) < 10 or len(federal["source_layers"]) < 25
            or len(enc.get("query_receipts", [])) != 18
            or sum(row["count"] for row in enc["query_receipts"]) != len(enc.get("features", []))
            or not enc["features"]):
        raise ValueError("Incomplete official GIS response")
    project = Transformer.from_crs("EPSG:4326", "EPSG:26910", always_xy=True).transform
    to_geo = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True).transform
    mpa_union = safe_union(mpa_features, project)
    gea_union = safe_union(geas, project)
    danger = [transform(project, shape(f["geometry"])) for f in enc["features"]]
    danger_zone_7 = transform(project, vandenberg_zone_7())
    query_envelope = box(*enc["bounds"])
    rows = []
    for survey_id, cells, footprint in candidates:
        if not query_envelope.covers(transform(to_geo, footprint.buffer(100))):
            raise ValueError("NOAA ENC query envelope omits candidate review margin")
        distances = [footprint.distance(mpa_union), footprint.distance(gea_union),
                     min(footprint.distance(item) for item in danger)]
        static_zone_7 = danger_zone_7.covers(footprint.buffer(100))
        rows.append({
            "survey_id": survey_id,
            "full_component_native_cells": cells,
            "full_component_area_m2": cells * 16,
            "nearest_cdfw_mpa_m": round(distances[0], 1),
            "nearest_noaa_gea_m": round(distances[1], 1),
            "nearest_noaa_enc_charted_danger_m": round(distances[2], 1),
            "within_100m_review_buffer": any(value <= 100 for value in distances),
            "inside_approximate_vandenberg_zone_7_with_100m_margin": static_zone_7,
            "launch_closure_status_for_trip_date": "unverified",
            "fishing_target": False,
            "exportable": False,
        })
    return {
        "schema_version": 1,
        "scope": "point-conception-two-original-4m-components-current-gis-screen",
        "review_margin_m": 100,
        "projected_crs": "EPSG:26910",
        "components": rows,
        "components_held_by_mapped_gis": sum(row["within_100m_review_buffer"] for row in rows),
        "cdfw_mpa_features": len(mpa_features),
        "noaa_gea_features": len(geas),
        "noaa_enc_danger_features": len(danger),
        "source_checked_at": {"cdfw_mpa": mpa_read["checked_at"],
                              "noaa_federal": federal["retrieved_at"], "noaa_enc": enc["checked_at"]},
        "source_urls": {"cdfw_mpa": mpa["source_url"],
                        "noaa_federal": federal["service_url"], "noaa_enc": enc["source_url"],
                        "vandenberg_zone_rule": VANDENBERG_ZONE_7_RULE,
                        "vandenberg_live_notice": VANDENBERG_LIVE_NOTICE},
        "vandenberg_rule_review": {
            "section": "33 CFR 334.1130(a)(2)(vii), (b)(1), (b)(3)–(5)",
            "source_up_to_date_as_of": "2026-09-24",
            "meaning": "Zone 7 ordinarily permits fishing and navigation, subject to announced launch closures; no trip-date clearance is inferred.",
            "geometry_note": "Static regulation perimeter uses a straight closing segment between shoreline endpoints; candidate inclusion is a research classification only.",
        },
        "source_feature_sha256": {"cdfw_mpa": feature_digest(mpa_features),
                                  "noaa_federal": feature_digest(federal["features"]),
                                  "noaa_enc": feature_digest(enc["features"])},
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "An official GIS proximity screen does not establish legal permission or chart clearance.",
            "Zone 7 launch closure status, other security notices, current method/species regulations and departure/return routes are not screened for a trip date.",
            "ENC Direct queried danger classes are not a complete navigational chart or route safety check.",
            "Source registration, independent habitat/fish evidence and current observations remain unresolved.",
            "Research component geometry is withheld from this aggregate receipt.",
        ],
    }


def verify_baseline(report, baseline):
    for key in ("scope", "components", "components_held_by_mapped_gis",
                "source_feature_sha256"):
        if report[key] != baseline.get(key):
            raise ValueError(f"Point Conception 4 m access screen changed: {key}; hold for review")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag-cache", type=Path, default=CACHE)
    parser.add_argument("--usgs-cache", type=Path, default=USGS_CACHE)
    parser.add_argument("--mpas", required=True, type=Path)
    parser.add_argument("--federal", required=True, type=Path)
    parser.add_argument("--enc", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    prior_path = ROOT / "dist/data/point-conception-original-4m-rugged-overlap.json"
    prior = json.loads(prior_path.read_text())
    sources = [args.mpas, args.federal, args.enc]
    report = audit(prior, *(json.loads(path.read_text()) for path in sources),
                   candidate_footprints(args.bag_cache, args.usgs_cache, prior))
    report["input_sha256"] = {key: sha256(path) for key, path in zip(
        ("rugged_overlap", "cdfw_mpas", "noaa_federal", "noaa_enc"),
        (prior_path, *sources))}
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        verify_baseline(report, baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"components": len(report["components"]),
                      "held": report["components_held_by_mapped_gis"]}))


if __name__ == "__main__":
    main()

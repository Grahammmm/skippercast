#!/usr/bin/env python3
"""Screen full Monterey 300 ft research outlines against fresh official GIS.

All outcomes remain research-only. A clear approximate GIS buffer is not legal
permission, a chart review, or a navigable fishing coordinate.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh(value, now, max_hours=36):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or not 0 <= (now - instant).total_seconds() <= max_hours * 3600:
        raise ValueError("Closure source is stale or future dated")
    return instant.isoformat()


def safe_union(features, project):
    geoms = []
    for feature in features:
        item = shape(feature["geometry"])
        if not item.is_valid and item.geom_type == "MultiPolygon":
            members = list(item.geoms)
            if any(not member.is_valid or member.is_empty for member in members):
                raise ValueError("Invalid closure member")
            repaired = unary_union(members)
            if not repaired.is_valid or any(not repaired.covers(member) for member in members):
                raise ValueError("Unreviewable closure overlap")
            item = repaired
        if item.is_empty or not item.is_valid:
            raise ValueError("Invalid closure geometry")
        geoms.append(transform(project, item))
    if not geoms:
        raise ValueError("Empty official closure feature set")
    return unary_union(geoms)


def official_query_envelope(source_url):
    url = urlsplit(source_url)
    values = parse_qs(url.query)
    if (url.hostname != "services2.arcgis.com"
            or "/biosds582_fpu/FeatureServer/0/query" not in url.path
            or values.get("geometryType") != ["esriGeometryEnvelope"]
            or values.get("inSR") != ["4326"]
            or values.get("spatialRel") != ["esriSpatialRelIntersects"]):
        raise ValueError("CDFW query coverage cannot be verified")
    coords = [float(part) for part in values["geometry"][0].split(",")]
    if len(coords) != 4 or not -125 <= coords[0] < coords[2] <= -116 or not 32 <= coords[1] < coords[3] <= 42:
        raise ValueError("Invalid CDFW query envelope")
    return box(*coords)


def screen_geometry(footprint, mpa_union, gea_union, buffer_m=100):
    if footprint.is_empty or not footprint.is_valid or not 0 < buffer_m <= 500:
        raise ValueError("Invalid research geometry or review margin")
    mpa_distance = footprint.distance(mpa_union)
    gea_distance = footprint.distance(gea_union)
    return {"nearest_cdfw_mpa_m": round(mpa_distance, 1),
            "nearest_noaa_gea_m": round(gea_distance, 1),
            "within_100m_closure_review_buffer": mpa_distance <= buffer_m or gea_distance <= buffer_m}


def audit(pixel, context, mpas, federal, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (pixel.get("scope") != "monterey-original-pixel-depth-band-audit"
            or pixel.get("fishing_target") is not False
            or pixel.get("outline_count", 0) < 1
            or len(pixel["outlines"]) != pixel["outline_count"]
            or len(context.get("features", [])) < pixel["outline_count"]
            or federal.get("status") != "ok"
            or federal.get("scope") != "noaa-west-coast-groundfish-conservation-areas"
            or len(federal.get("source_layers", [])) < 25):
        raise ValueError("Incomplete original habitat or federal-area review")
    all_mpas = []
    query_envelopes = []
    for region, item in zip(("santa-cruz-monterey-bay", "monterey-point-sur"), mpas):
        if item.get("region_id") != region or len(item.get("features", [])) < 8:
            raise ValueError("Wrong or incomplete regional CDFW MPA source")
        fresh(item["checked_at"], now)
        query_envelopes.append(official_query_envelope(item["source_url"]))
        all_mpas.extend(item["features"])
    fresh(federal["retrieved_at"], now)
    geas = [row for row in federal["features"] if row["properties"]["area_type"] == "GEA"]
    if len(geas) < 10:
        raise ValueError("NOAA GEA source incomplete")
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    mpa_union = safe_union(all_mpas, project)
    mpa_query_coverage = unary_union([transform(project, envelope) for envelope in query_envelopes])
    gea_union = safe_union(geas, project)
    features = {feature["properties"]["id"]: feature for feature in context["features"]}
    results = []
    for row in pixel["outlines"]:
        ident = row["context_id"]
        feature = features.get(ident)
        if not feature or feature["properties"].get("fishing_target") is not False:
            raise ValueError("Original Monterey habitat identity changed")
        footprint = transform(project, shape(feature["geometry"]))
        if not mpa_query_coverage.covers(footprint.buffer(100)):
            raise ValueError("Official CDFW queries do not cover the full research buffer")
        result = screen_geometry(footprint, mpa_union, gea_union)
        results.append({"context_id": ident,
                        "native_200_300ft_navd88_cells": row["native_cells_200_300ft_below_navd88"],
                        **result, "fishing_target": False, "exportable": False})
    return {"schema_version": 1, "scope": "monterey-original-300-research-closure-screen",
            "audited_at": now.isoformat(), "projected_crs": "EPSG:32610", "buffer_m": 100,
            "cdfw_mpa_features": len(all_mpas), "noaa_gea_features": len(geas),
            "cdfw_checked_at": [row["checked_at"] for row in mpas],
            "noaa_retrieved_at": federal["retrieved_at"],
            "outline_count": len(results),
            "held_within_100m_count": sum(row["within_100m_closure_review_buffer"] for row in results),
            "outlines": results, "fishing_target": False, "exportable": False,
            "limitations": "Approximate MPA/GEA GIS screen only. NAVD88 has not been converted to MLLW; source uncertainty, current species rules, USCG/security notices, NOAA ENC dangers and transit remain unreviewed for these outlines. No fishing or navigation permission is inferred."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pixel", type=Path, default=Path("dist/data/monterey-original-300-pixel-review.json"))
    parser.add_argument("--context", type=Path, default=Path("dist/data/usgs-offshore-monterey-hard-context.geojson"))
    parser.add_argument("--mpa-north", type=Path, default=Path("dist/regions/santa-cruz-monterey-bay/protected-areas.geojson"))
    parser.add_argument("--mpa-south", type=Path, default=Path("dist/regions/monterey-point-sur/protected-areas.geojson"))
    parser.add_argument("--federal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {"pixel": args.pixel, "context": args.context, "mpa_north": args.mpa_north,
             "mpa_south": args.mpa_south, "federal": args.federal}
    loaded = {key: json.loads(path.read_text()) for key, path in paths.items()}
    report = audit(loaded["pixel"], loaded["context"],
                   [loaded["mpa_north"], loaded["mpa_south"]], loaded["federal"])
    report["input_sha256"] = {key: digest(path) for key, path in paths.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['held_within_100m_count']}/{report['outline_count']} research outlines held by approximate GIS buffer; zero fishing targets")


if __name__ == "__main__":
    main()

"""Recheck a research shortlist against fresh complete CDFW MPAs and NOAA GEAs.

This is a conservative source-screen receipt, never fishing or navigation approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import atomic_json


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_time(value: str, now: datetime, max_hours: float) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    age = (now - instant).total_seconds() / 3600
    if instant.tzinfo is None or not 0 <= age <= max_hours:
        raise ValueError("Closure geometry is stale or future-dated")
    return instant.isoformat()


def audit(queue: dict, context: dict, coastal: dict, federal: dict, *, now=None,
          buffer_m=100, context_scope="northern-native-noaa-usgs-hard-bottom-context",
          projected_crs="EPSG:32610") -> dict:
    now = now or datetime.now(timezone.utc)
    mpa = coastal.get("sources", {}).get("mpas", {})
    if (queue.get("scope") != "original-habitat-site-review-queue"
            or queue.get("fishing_target") is not False
            or context.get("scope") != context_scope
            or mpa.get("status") != "ok"
            or federal.get("status") != "ok"
            or federal.get("scope") != "noaa-west-coast-groundfish-conservation-areas"
            or not 0 < buffer_m <= 500):
        raise ValueError("Unreviewed input scope or closure source")
    checked_time(mpa["data_retrieved_at"], now, mpa["max_age_hours"])
    checked_time(federal["retrieved_at"], now, 36)
    mpa_data = mpa["data"]
    mpa_features = mpa_data["geojson"]["features"]
    if len(mpa_features) != mpa_data["feature_count"] or len(mpa_features) < 100:
        raise ValueError("Incomplete statewide CDFW MPA geometry")
    if len(federal["features"]) != federal["feature_count"] or len(federal["source_layers"]) < 25:
        raise ValueError("Incomplete NOAA federal geometry")
    geas = [f for f in federal["features"] if f["properties"]["area_type"] == "GEA"]
    if len(geas) < 10:
        raise ValueError("Incomplete NOAA GEA geometry")
    target = CRS.from_user_input(projected_crs)
    if (not target.is_projected or not target.axis_info
            or any(axis.unit_name.lower() not in ("metre", "meter") for axis in target.axis_info)):
        raise ValueError("Closure distance CRS must be projected in meters")
    project = Transformer.from_crs("EPSG:4326", target, always_xy=True).transform
    def union(features):
        geometries = []
        for feature in features:
            geometry = shape(feature["geometry"])
            if not geometry.is_valid and geometry.geom_type == "MultiPolygon":
                # CDFW serializes three nested special-closure shells as
                # overlapping members. Preserve every original member.
                members = list(geometry.geoms)
                if any(member.is_empty or not member.is_valid for member in members):
                    raise ValueError("Invalid closure member")
                repaired = unary_union(members)
                if not repaired.is_valid or any(not repaired.covers(member) for member in members):
                    raise ValueError("Conservative closure repair failed")
                geometry = repaired
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError("Invalid closure geometry")
            geometries.append(transform(project, geometry))
        return unary_union(geometries)
    mpa_union = union(mpa_features)
    gea_union = union(geas)
    by_id = {f["properties"]["id"]: f for f in context["features"]}
    rows = queue["research_shortlist"]
    if (len(by_id) != queue["source_context_outlines"]
            or len(rows) != queue["research_shortlist_count"]
            or len({r["context_id"] for r in rows}) != len(rows)):
        raise ValueError("Incomplete or duplicate original habitat shortlist")
    results = []
    for row in rows:
        ident = row["context_id"]
        feature = by_id[ident]
        if (row.get("fishing_target") is not False
                or feature["properties"].get("fishing_target") is not False
                or row["survey_id"] != feature["properties"]["survey_id"]):
            raise ValueError("Research-only status or survey identity changed")
        footprint = transform(project, shape(feature["geometry"]))
        if footprint.is_empty or not footprint.is_valid:
            raise ValueError("Invalid habitat outline")
        mpa_m = footprint.distance(mpa_union)
        gea_m = footprint.distance(gea_union)
        held = mpa_m <= buffer_m or gea_m <= buffer_m
        results.append({"context_id": ident, "survey_id": row["survey_id"],
                        "nearest_cdfw_mpa_m": round(mpa_m, 1),
                        "nearest_noaa_gea_m": round(gea_m, 1),
                        "within_closure_review_buffer": held,
                        "closure_screen": "held" if held else "no-mapped-overlap-with-buffer",
                        "fishing_target": False, "exportable": False})
    return {"schema_version": 1, "scope": "original-habitat-shortlist-fresh-closure-audit",
            "shortlist_count": len(results), "held_count": sum(r["within_closure_review_buffer"] for r in results),
            "buffer_m": buffer_m, "projected_crs": projected_crs, "context_scope": context_scope,
            "cdfw_mpa_count": len(mpa_features), "noaa_gea_count": len(geas),
            "cdfw_retrieved_at": mpa["data_retrieved_at"],
            "cdfw_source_url": mpa_data["source_url"],
            "noaa_retrieved_at": federal["retrieved_at"],
            "noaa_source_url": federal["service_url"],
            "audited_at": now.isoformat(timespec="seconds"), "outlines": results,
            "fishing_target": False, "exportable": False,
            "limitations": "Approximate GIS polygons and historical habitat outlines. A clear geometry screen is not legal permission, current chart clearance, safe access, current fish presence, or a route/harbor assessment. Current regulations and exact legal boundaries control."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue", type=Path, default=Path("dist/data/cape-mendocino-original-habitat-site-review-queue.json"))
    p.add_argument("--context", type=Path, default=Path("dist/data/cape-mendocino-native-hard-context.geojson"))
    p.add_argument("--coastal", type=Path, required=True)
    p.add_argument("--federal", type=Path, required=True)
    p.add_argument("--context-scope", default="northern-native-noaa-usgs-hard-bottom-context")
    p.add_argument("--projected-crs", default="EPSG:32610")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    paths = {"queue": args.queue, "context": args.context, "coastal": args.coastal, "federal": args.federal}
    data = audit(*(json.loads(path.read_text()) for path in paths.values()),
                 context_scope=args.context_scope, projected_crs=args.projected_crs)
    data["input_sha256"] = {name: digest(path) for name, path in paths.items()}
    atomic_json(args.output, data)
    print(json.dumps({"shortlist": data["shortlist_count"], "held": data["held_count"]}))


if __name__ == "__main__":
    main()

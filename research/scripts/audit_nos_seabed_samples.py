#!/usr/bin/env python3
"""Screen historic NOAA/NOS bottom samples near private research areas.

This is a gap audit, not a substrate validator or a fishing-spot generator.
Only aggregate distances and counts are written; exact samples and research
geometries remain outside the public artifact.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[2]
SERVICE = "https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/nos_seabed_dynamic/MapServer/0"
ENVELOPE = [-122.3, 34.3, -120.0, 36.9]
SOURCES = {
    "monterey": (ROOT / "dist/data/usgs-offshore-monterey-hard-context.geojson", "EPSG:4326"),
    "point_buchon": (ROOT / "var/review/point-buchon-2009-csumb-100m-blocks.geojson", "EPSG:32610"),
    "estero": (ROOT / "var/review/estero-nominal-research-blocks.geojson", "EPSG:32610"),
}


def fetch_samples():
    query = {
        "f": "json", "where": "1=1", "geometry": ",".join(map(str, ENVELOPE)),
        "geometryType": "esriGeometryEnvelope", "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields":
        "SURVEY,SAMPLE,LAT,LON,BEGIN_OBSTIM,DESCRP,NATSUR,NATQUA,SOURCE,SORDAT",
        "returnGeometry": "true", "resultRecordCount": "2000",
    }
    request = Request(SERVICE + "/query?" + urlencode(query), headers={"User-Agent": "SkipperCast-source-audit/1.0"})
    with urlopen(request, timeout=60) as response:
        data = json.load(response)
    if "error" in data or data.get("exceededTransferLimit") or len(data.get("features", [])) >= 2000:
        raise ValueError("NOAA query failed or result may be incomplete")
    if data.get("spatialReference", {}).get("wkid") != 4326:
        raise ValueError("NOAA response CRS changed")
    return data["features"]


def areas(selected=None):
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
    matrix = json.loads((ROOT / "research/receipts/monterey-original-300-paired-review.json").read_text())
    monterey_ids = {row["context_id"] for row in matrix["outlines"]}
    if len(monterey_ids) != 17:
        raise ValueError("Monterey research matrix changed")
    result = {}
    for name, (path, crs) in SOURCES.items():
        if selected is not None and name not in selected:
            continue
        layer = json.loads(path.read_text())
        geometries = []
        for feature in layer["features"]:
            props = feature.get("properties", {})
            if props.get("fishing_target") is not False:
                continue
            if name == "monterey" and props.get("id") not in monterey_ids:
                # The public context includes a larger habitat layer.
                continue
            geom = shape(feature["geometry"])
            if crs == "EPSG:4326":
                geom = transform(project.transform, geom)
            if not geom.is_empty:
                geometries.append(geom)
        result[name] = geometries
    return result


def audit(samples, candidate_areas):
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
    rows = []
    for feature in samples:
        a = feature["attributes"]
        geom = feature.get("geometry", {})
        if not all(isinstance(geom.get(k), (int, float)) for k in ("x", "y")):
            raise ValueError("Missing sample geometry")
        point = transform(project.transform, Point(geom["x"], geom["y"]))
        when = a.get("BEGIN_OBSTIM") or a.get("SORDAT")
        if isinstance(when, (int, float)):
            year = datetime.fromtimestamp(when / 1000, tz=timezone.utc).year
        else:
            year = None
        rows.append((point, year, a.get("SURVEY"), a.get("SOURCE"), a.get("DESCRP") or ""))
    summary = {}
    for name, geoms in candidate_areas.items():
        if not geoms:
            summary[name] = {"research_areas": 0, "nearest_sample_m": None}
            continue
        distances = [(min(g.distance(point) for g in geoms), year, survey, source, description)
                     for point, year, survey, source, description in rows]
        distances.sort(key=lambda x: x[0])
        summary[name] = {
            "research_areas": len(geoms),
            "samples_inside": sum(d == 0 for d, *_ in distances),
            "samples_within_100m": sum(d <= 100 for d, *_ in distances),
            "samples_within_500m": sum(d <= 500 for d, *_ in distances),
            "within_100m_descriptions": dict(sorted(Counter(description or "unspecified" for d, _, _, _, description in distances if d <= 100).items())),
            "within_100m_survey_years": dict(sorted(Counter(f"{survey or 'unknown'} ({year or 'undated'})" for d, year, survey, _, _ in distances if d <= 100).items())),
            "nearest_sample_m": round(distances[0][0], 1) if distances else None,
            "nearest_sample_year": distances[0][1] if distances else None,
            "nearest_sample_survey": distances[0][2] if distances else None,
            "nearest_sample_description": distances[0][4] if distances else None,
            "nearest_sample_source": distances[0][3] if distances else None,
        }
    return {
        "schema_version": 1, "scope": "central-coast-nos-seabed-historic-research-gap",
        "source_url": SERVICE, "query_envelope_wgs84": ENVELOPE,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "returned_samples": len(rows),
        "source_counts": dict(sorted(Counter(r[3] or "unknown" for r in rows).items())),
        "survey_counts": dict(sorted(Counter(r[2] or "unknown" for r in rows).items())),
        "year_counts": dict(sorted(Counter(str(r[1]) for r in rows).items())),
        "area_summary": summary,
        "fishing_target": False, "exportable": False,
        "limitations": [
            "Historic point descriptions are sparse and may have unbounded horizontal error.",
            "A nearby sample cannot validate a small reef or fish presence without survey precision and direct overlap.",
            "No exact sample or private research coordinates are published by this audit.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "research/receipts/nos-seabed-central-gap-audit.json")
    parser.add_argument("--scope", choices=(*SOURCES, "all"), default="all")
    args = parser.parse_args()
    selected = None if args.scope == "all" else {args.scope}
    result = audit(fetch_samples(), areas(selected))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"returned_samples": result["returned_samples"], "area_summary": result["area_summary"]}, indent=2))


if __name__ == "__main__":
    main()

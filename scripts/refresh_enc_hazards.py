"""Snapshot NOAA ENC Direct danger geometry for a bounded review scope.

This checks charted danger features, not chart completeness, safe routing, or
fishing permission. A changed or unavailable layer fails the whole refresh.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://encdirect.noaa.gov/arcgis/rest/services/encdirect"
SERVICES = ("enc_harbour", "enc_approach", "enc_coastal")
LAYERS = ("Obstruction_point", "Underwater_Awash_Rock_point", "Wreck_point",
          "Obstruction_line", "Obstruction_area", "Wreck_area")


def fetch_json(url):
    if not url.startswith(BASE + "/"):
        raise ValueError("ENC URL is outside the reviewed NOAA host and service")
    request = urllib.request.Request(url, headers={"User-Agent": "SkipperCast NOAA ENC hazard review/1.0"})
    with urllib.request.urlopen(request, timeout=35) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("ENC source status or redirect changed")
        raw = response.read(6_000_001)
    if not raw or len(raw) > 6_000_000:
        raise ValueError("ENC response is empty or oversized")
    result = json.loads(raw)
    if "error" in result:
        raise ValueError("ENC service reported an error: " + str(result["error"])[:180])
    return result, hashlib.sha256(raw).hexdigest()


def query_layer(service, layer, layer_id, bounds):
    root = f"{BASE}/{service}/MapServer/{layer_id}/query"
    common = {"where": "1=1", "geometry": ",".join(map(str, bounds)),
              "geometryType": "esriGeometryEnvelope", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects"}
    count_url = root + "?" + urllib.parse.urlencode({**common, "returnCountOnly": "true", "f": "json"})
    count, count_sha = fetch_json(count_url)
    if type(count.get("count")) is not int or not 0 <= count["count"] <= 1000:
        raise ValueError("ENC count is missing or exceeds the bounded query budget")
    data_url = root + "?" + urllib.parse.urlencode({**common, "outFields": "*",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson"})
    data, data_sha = fetch_json(data_url)
    features = data.get("features")
    if (data.get("type") != "FeatureCollection" or not isinstance(features, list)
            or data.get("exceededTransferLimit") or len(features) != count["count"]):
        raise ValueError("Incomplete or changed ENC feature response")
    for feature in features:
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Point", "LineString", "Polygon", "MultiPolygon"):
            raise ValueError("Unsupported ENC danger geometry")
        feature["properties"] = {**feature.get("properties", {}),
            "enc_service": service, "enc_layer": layer, "enc_layer_id": layer_id}
    return features, {"service": service, "layer": layer, "layer_id": layer_id,
        "count": count["count"], "count_url": count_url, "count_sha256": count_sha,
        "data_url": data_url, "data_sha256": data_sha}


def refresh(scope, output):
    bounds = scope["bounds"]
    if (len(bounds) != 4 or not -125 <= bounds[0] < bounds[2] <= -116
            or not 32 <= bounds[1] < bounds[3] <= 42):
        raise ValueError("ENC review bounds must be a bounded California envelope")
    jobs = []
    for service in SERVICES:
        url = f"{BASE}/{service}/MapServer?f=pjson"
        metadata, digest = fetch_json(url)
        names = {row["name"]: row["id"] for row in metadata.get("layers", [])}
        if len(names) != len(metadata.get("layers", [])):
            raise ValueError("Duplicate ENC layer name")
        prefix = {"enc_harbour": "Harbor", "enc_approach": "Approach", "enc_coastal": "Coastal"}[service]
        for layer in LAYERS:
            full = prefix + "." + layer
            if full not in names:
                raise ValueError("Required NOAA ENC layer missing: " + full)
            jobs.append((service, layer, names[full], bounds))
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(lambda args: query_layer(*args), jobs))
    features = [feature for batch, _ in rows for feature in batch]
    receipts = [receipt for _, receipt in rows]
    result = {"schema_version": 1, "type": "FeatureCollection",
        "region_id": scope["region_id"], "scope_id": scope["id"], "bounds": bounds,
        "checked_at": datetime.now(timezone.utc).isoformat(), "source_url": BASE,
        "status": "charted-danger-screen-only", "query_receipts": receipts,
        "limitations": "NOAA ENC Direct danger features across three scale bands. Retrieval is not an ENC issue time, chart completeness certification, navigation clearance or safe route. Source-date attributes can be older than the service refresh. Empty layers are checked, not assumed. Other hazards and local restrictions require separate review.",
        "features": features}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    temporary.replace(output)
    return {"scope_id": scope["id"], "features": len(features),
        "queried_layers": len(receipts), "checked_at": result["checked_at"], "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--output", type=Path,
        help="Optional unpublished var/ review or data-feed output")
    args = parser.parse_args()
    config = json.loads((ROOT / "catalog/noaa-enc-hazard-scopes.json").read_text())
    if config.get("source_url") != BASE or config.get("schema_version") != 1:
        raise ValueError("Unreviewed NOAA ENC provider config")
    scopes = [row for row in config["scopes"] if row["id"] == args.scope]
    if len(scopes) != 1:
        raise ValueError("Unknown or duplicate NOAA ENC scope")
    if scopes[0].get("research_only") and args.output is None:
        raise ValueError("Research-only ENC scopes require an explicit unpublished var/review/ output")
    output = args.output or ROOT / scopes[0]["output"]
    output = output.resolve()
    if args.output:
        if not output.is_relative_to((ROOT / "var").resolve()):
            raise ValueError("Unpublished ENC output must stay under var/")
        if scopes[0].get("research_only") and not output.is_relative_to((ROOT / "var/review").resolve()):
            raise ValueError("Research-only ENC output must stay under var/review/")
    elif not output.is_relative_to((ROOT / "dist/regions" / scopes[0]["region_id"]).resolve()):
        raise ValueError("ENC output escaped its regional package")
    print(json.dumps(refresh(scopes[0], output)))


if __name__ == "__main__":
    main()

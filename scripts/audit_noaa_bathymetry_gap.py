"""Check NOAA's bathymetry coverage map as a *discovery* aid only.

The ~100 m coverage class is not an elevation, survey-quality test, or
fishing-target input. Keep the live service's metadata and a few known probes
in a receipt so a changed service cannot silently change source triage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from skippercast.platform.contracts import atomic_json


ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/4d7d925fc96d47d9ace970dd5040df0a?f=json"
SERVICE = "https://gis.ngdc.noaa.gov/arcgis/rest/services/bathy_gap_analysis/MapServer"
PROBES = (
    ("off-point-conception", 34.45, -120.55),
    ("off-morro-bay", 35.30, -120.90),
    ("off-south-big-sur", 35.80, -121.40),
    ("off-monterey-bay", 36.60, -121.90),
)


def fetch(url: str) -> tuple[dict, str]:
    if not (url == ITEM_URL or url.startswith(SERVICE + "?f=json") or
            url.startswith(SERVICE + "/identify?")):
        raise ValueError("Unreviewed coverage service URL")
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast source audit/1.0"}), timeout=30) as response:
        raw = response.read(1_000_001)
        if response.status != 200 or not raw or len(raw) > 1_000_000:
            raise ValueError("NOAA coverage source unavailable or oversized")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def identify_url(lat: float, lon: float) -> str:
    params = {
        "f": "json", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "sr": 4326, "layers": "all:0,1", "tolerance": 1,
        "mapExtent": f"{lon-.005},{lat-.005},{lon+.005},{lat+.005}",
        "imageDisplay": "1024,1024,96", "returnGeometry": "false",
    }
    return SERVICE + "/identify?" + urlencode(params)


def classify(results: list[dict]) -> str:
    if {item.get("layerId") for item in results} != {0, 1}:
        raise ValueError("Incomplete NOAA coverage identify response")
    opaque = []
    for item in results:
        if item.get("layerId") not in (0, 1):
            raise ValueError("Unexpected coverage layer")
        attrs = item.get("attributes") or {}
        alpha = int(attrs.get("RGB.Alpha", -1))
        if alpha not in (0, 255):
            raise ValueError("Unexpected coverage pixel transparency")
        if alpha == 255:
            opaque.append(item["layerId"])
    if len(opaque) > 1:
        raise ValueError("Overlapping NOAA coverage classes")
    return {0: "three-or-more-or-coverage-footprint", 1: "one-or-two", None: "no-class-at-probe"}[opaque[0] if opaque else None]


def audit() -> dict:
    item, item_hash = fetch(ITEM_URL)
    service, service_hash = fetch(SERVICE + "?f=json")
    if (item.get("url") != SERVICE or item.get("access") != "public" or
            [(x.get("id"), x.get("name")) for x in service.get("layers", [])] != [
                (0, "3 or more soundings per ~100m cell"),
                (1, "1-2 soundings per ~100m cell"),
            ]):
        raise ValueError("NOAA bathymetry coverage identity/schema changed")
    probes = []
    for name, lat, lon in PROBES:
        data, sha = fetch(identify_url(lat, lon))
        if "error" in data:
            raise ValueError(f"NOAA coverage probe failed: {name}")
        probes.append({"id": name, "latitude": lat, "longitude": lon,
                       "coverage_class": classify(data.get("results", [])), "response_sha256": sha})
    return {
        "schema_version": 1,
        "scope": "central-noaa-bathymetry-coverage-discovery",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": "https://iocm.noaa.gov/seabed-2030-bathymetry.html",
        "item_url": ITEM_URL,
        "service_url": SERVICE,
        "item_sha256": item_hash,
        "service_sha256": service_hash,
        "item_modified_epoch_ms": item.get("modified"),
        "layer_names": [x["name"] for x in service["layers"]],
        "probes": probes,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "NOAA's ~100 m coverage classes indicate archived soundings or survey footprints, not cell depth, native resolution, uncertainty, bottom type, or fish.",
            "Class 0 includes coverage footprints assigned a better-mapped value even where a local soundings count was not separately established.",
            "A transparent probe is only an absence of this coverage class at that sample, not proof that the seabed has never been surveyed.",
            "These four isolated probes do not measure sector-wide coverage or qualify any fishing spot."
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = audit()
    if args.verify:
        baseline = json.loads(args.verify.read_text())
        comparison = lambda row: (row["item_modified_epoch_ms"], row["layer_names"],
                                  [(p["id"], p["coverage_class"]) for p in row["probes"]])
        if comparison(result) != comparison(baseline):
            raise ValueError("NOAA coverage layer or sample changed; review source triage")
    atomic_json(args.output, result)
    print(json.dumps({"probes": len(result["probes"]), "fishing_target": False}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Research-only MPA/ENC proximity screen for private Point Buchon 100 m blocks.

Publish aggregate counts, not candidate geometries. A clean block is not a
lawful fishing target: date/method rules, special closures, routes and full
charted footprint remain separate release gates.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform
from shapely.strtree import STRtree
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repository root, for research.*
from research.lib.receipts import locate


ROOT = Path(__file__).resolve().parents[2]
INPUTS = {
    "rov_blocks": "var/review/point-buchon-rov-100m-blocks.geojson",
    "terrain_blocks": "var/review/point-buchon-2009-csumb-100m-blocks.geojson",
    "cdfw_mpas": "var/review/point-buchon-cdfw-mpas.geojson",
    "noaa_enc": "var/review/enc-hazards-point-buchon-open-reference.geojson",
}
EXPECTED_MPAS = {"Morro Bay SMRMA", "Point Buchon SMCA", "Point Buchon SMR"}
MPA_QUERY_BOUNDS = [-121.02, 35.10, -120.79, 35.33]


def audit(inputs):
    for key, count in (("rov_blocks", 26), ("terrain_blocks", 181)):
        if inputs[key].get("crs") != "EPSG:32610" or len(inputs[key].get("features", [])) != count:
            raise ValueError(f"{key} private block source changed")
    mpa = inputs["cdfw_mpas"]
    if {f["properties"]["NAME"] for f in mpa.get("features", [])} != EXPECTED_MPAS:
        raise ValueError("CDFW Point Buchon MPA identity set changed")
    if mpa.get("crs", {}).get("properties", {}).get("name") != "EPSG:4326":
        raise ValueError("Unexpected CDFW MPA CRS")
    enc = inputs["noaa_enc"]
    if (enc.get("scope_id") != "point-buchon-open-reference-hard-context"
            or len(enc.get("query_receipts", [])) != 18
            or sum(r["count"] for r in enc["query_receipts"]) != len(enc.get("features", []))):
        raise ValueError("NOAA ENC source scope or layer receipt changed")
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform
    mpas = {f["properties"]["NAME"]: transform(project, shape(f["geometry"]))
            for f in mpa["features"]}
    hazards = [transform(project, shape(f["geometry"])) for f in enc["features"]]
    if not hazards:
        raise ValueError("Empty ENC hazard screen cannot imply clean blocks")
    if len(enc.get("bounds", [])) != 4:
        raise ValueError("NOAA ENC query bounds missing")
    enc_bounds = transform(project, box(*enc["bounds"]))
    mpa_query_bounds = transform(project, box(*MPA_QUERY_BOUNDS))
    tree = STRtree(hazards)
    groups = {}
    for key in ("rov_blocks", "terrain_blocks"):
        blocks = [shape(f["geometry"]) for f in inputs[key]["features"]]
        if any(b.is_empty or not b.is_valid for b in blocks):
            raise ValueError("Invalid private research block")
        if any(not enc_bounds.covers(b.buffer(250)) for b in blocks):
            raise ValueError("NOAA ENC query does not cover every 250 m block buffer")
        if any(not mpa_query_bounds.covers(b.buffer(100)) for b in blocks):
            raise ValueError("CDFW MPA query does not cover every 100 m block buffer")
        mpa_counts = {name: {"intersects": sum(b.intersects(poly) for b in blocks),
                             "within_100m": sum(b.distance(poly) <= 100 for b in blocks)}
                      for name, poly in sorted(mpas.items())}
        groups[key] = {
            "block_count": len(blocks),
            "mpa": mpa_counts,
            "any_mpa_intersection": sum(any(b.intersects(p) for p in mpas.values()) for b in blocks),
            "any_mpa_within_100m": sum(any(b.distance(p) <= 100 for p in mpas.values()) for b in blocks),
            "any_enc_feature_within_100m": sum(len(tree.query(b.buffer(100))) > 0 for b in blocks),
            "any_enc_feature_within_250m": sum(len(tree.query(b.buffer(250))) > 0 for b in blocks),
            "legal_route_hazard_gate_satisfied": False,
            "fishing_target": False,
        }
    return {
        "schema_version": 1,
        "scope": "point-buchon-private-100m-blocks-cdfw-mpa-noaa-enc-research-screen",
        "cdfw_checked_at": mpa["checked_at"], "cdfw_source_url": mpa["source_url"],
        "noaa_enc_checked_at": enc["checked_at"], "noaa_enc_source_url": enc["source_url"],
        "noaa_enc_feature_count": len(hazards), "noaa_enc_layer_count": 18,
        "cdfw_query_bounds": MPA_QUERY_BOUNDS,
        "projected_crs": "EPSG:32610", "groups": groups,
        "full_footprint_legal_chart_access_verified": False,
        "fishing_target": False, "exportable": False,
        "limitations": "Proximity to three CDFW MPA polygons and this NOAA ENC Direct danger-layer snapshot only. Other state/federal closures, security areas, regulations by species/date/method, chart completeness, approaches and return routes have not been cleared. ENC Direct is not certified navigation data. No depth, substrate, fish or position-error qualification is inferred.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("research/receipts/point-buchon-private-block-access-screen.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    inputs = {key: json.loads(locate(path, root).read_text()) for key, path in INPUTS.items()}
    report = audit(inputs)
    report["source_sha256"] = {key: hashlib.sha256(locate(path, root).read_bytes()).hexdigest()
                                for key, path in INPUTS.items()}
    report["audited_at"] = datetime.now(timezone.utc).isoformat()
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("Point Buchon MPA/ENC research proximity checked; zero legal fishing targets")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Query NOAA NOS BAG catalog over the exact Estero research-block envelope.

Catalog absence is a bounded discovery result, not proof of no other survey.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from research.lib.paths import ROOT

from research.scripts.audit_estero_wgs84_direct import check_inputs, stable
from scripts.discover_noaa_surveys import scan
from skippercast.platform.contracts import atomic_json


BLOCKS = ROOT / "var/review/estero-nominal-research-blocks.geojson"
SOURCE_RECEIPT = ROOT / "dist/data/estero-wgs84-direct-vdatum-review.json"
DEPTH = ROOT / "var/review/estero-bay-2012/WGS84_utm10_EsteroBay.zip"
METADATA = ROOT / "var/review/estero-bay-2012/WGS84_metadata_EsteroBay.xml"
OUTPUT = ROOT / "dist/data/estero-noaa-bag-catalog-gap.json"


def build(blocks: dict, receipt: dict, depth: Path, metadata: Path,
          *, validate=check_inputs, scan_fn=scan) -> dict:
    fingerprint = validate(blocks, depth, metadata)
    if (receipt.get("scope") != "estero-2012-original-wgs84-direct-vdatum-research"
            or receipt.get("private_block_fingerprint") != fingerprint
            or receipt.get("sample_count") != 60
            or receipt.get("fishing_target") is not False):
        raise ValueError("Estero source/block identity changed")
    if blocks.get("crs") != "EPSG:32610" or len(blocks.get("features", [])) != 60:
        raise ValueError("Private Estero block set changed")
    geometry = unary_union([shape(feature["geometry"]) for feature in blocks["features"]])
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("Private Estero block envelope invalid")
    to_geo = Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True).transform
    bounds = transform(to_geo, geometry).bounds
    catalog = scan_fn([{"id": "estero-60-research-block-envelope", "bounds": bounds}])
    if catalog.get("health", {}).get("status") != "ok" or len(catalog.get("sectors", [])) != 1:
        raise ValueError("Fresh NOAA survey catalog query unavailable")
    query = catalog["sectors"][0]
    if query.get("status") != "ok" or not query.get("raw_sha256"):
        raise ValueError("Fresh NOAA survey catalog response unavailable")
    ids = sorted(row["id"] for row in query["surveys"])
    return {
        "schema_version": 1,
        "scope": "estero-60-research-block-noaa-nos-bag-catalog-gap",
        "source": catalog["source_url"],
        "private_block_fingerprint": fingerprint,
        "rounded_query_envelope_wgs84": [math.floor(bounds[0] * 100) / 100,
                                        math.floor(bounds[1] * 100) / 100,
                                        math.ceil(bounds[2] * 100) / 100,
                                        math.ceil(bounds[3] * 100) / 100],
        "exact_request_url_sha256": hashlib.sha256(query["request_url"].encode()).hexdigest(),
        "raw_response_sha256": query["raw_sha256"],
        "bag_survey_ids_returned": ids,
        "bag_survey_count": len(ids),
        "surveyed_depth_cells_confirmed": 0,
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "This is a fresh NOS BAG catalog polygon-envelope query over 60 private 100 m research blocks; it is not a search of every NOAA, USGS or private multibeam archive.",
            "A catalog hit would still require inspection of exact original measured cells, MLLW datum, uncertainty and source age. A zero hit does not establish absence of seabed structure or fish.",
            "The rounded published envelope is only a broad discovery area; individual block geometry and candidate positions remain unpublished.",
            "The independent 2012 Estero WGS84 source still lacks released CARIS TPU and a full cellwise VDatum/error surface; this result does not clear depth, substrate, law, hazards or routes.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=Path, default=BLOCKS)
    parser.add_argument("--source-receipt", type=Path, default=SOURCE_RECEIPT)
    parser.add_argument("--depth", type=Path, default=DEPTH)
    parser.add_argument("--metadata", type=Path, default=METADATA)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = build(json.loads(args.blocks.read_text()),
                   json.loads(args.source_receipt.read_text()), args.depth, args.metadata)
    if args.verify and stable(result) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("Estero NOS BAG catalog lead set changed; inspect before use")
    atomic_json(args.output, result)
    print(json.dumps({"bag_survey_ids": result["bag_survey_ids_returned"],
                      "fishing_target": False}))


if __name__ == "__main__":
    main()

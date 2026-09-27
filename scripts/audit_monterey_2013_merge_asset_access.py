#!/usr/bin/env python3
"""Check NOAA's published 2612 supplemental listings for missing merge inputs.

This is a bounded *availability* audit. A missing filename under these prefixes
does not prove the NOAA accuracy/source-inventory deliverables do not exist.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BUCKET = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/"
PREFIXES = ("laz/geoid18/2612/supplemental/", "laz/geoid12a/2612/supplemental/")
WANTED = ("accuracy", "inventory", "source", "acoustic", ".gdb", ".fgdb")
OUTPUT = ROOT / "dist/data/monterey-2013-merge-public-asset-access.json"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


def parse_listing(data, prefix):
    root = ET.fromstring(data)
    if root.tag != "{http://s3.amazonaws.com/doc/2006-03-01/}ListBucketResult":
        raise ValueError("NOAA listing response is not S3 ListBucketResult")
    if root.findtext("s:Prefix", namespaces=NS) != prefix:
        raise ValueError("NOAA listing prefix changed")
    if root.findtext("s:IsTruncated", namespaces=NS) != "false":
        raise ValueError("NOAA supplemental listing needs pagination")
    rows = []
    for item in root.findall("s:Contents", NS):
        key = item.findtext("s:Key", namespaces=NS)
        if not key or not key.startswith(prefix):
            raise ValueError("NOAA listing contains an unexpected key")
        rows.append({
            "key": key,
            "bytes": int(item.findtext("s:Size", namespaces=NS)),
            "last_modified": item.findtext("s:LastModified", namespaces=NS),
        })
    if len(rows) != int(root.findtext("s:KeyCount", namespaces=NS)):
        raise ValueError("NOAA listing key count changed")
    return sorted(rows, key=lambda item: item["key"])


def audit(fetch=None):
    if fetch is None:
        def fetch(url):
            with urlopen(Request(url, headers={"User-Agent": "SkipperCast-source-access-audit/1.0"}), timeout=25) as response:
                return response.read(1_000_001)
    listings = []
    for prefix in PREFIXES:
        url = BUCKET + "?" + urlencode({"list-type": "2", "prefix": prefix, "max-keys": "1000"})
        data = fetch(url)
        if len(data) > 1_000_000:
            raise ValueError("NOAA listing exceeded review bound")
        listings.append({"prefix": prefix, "listing_url": url, "objects": parse_listing(data, prefix)})
    matches = [item["key"] for listing in listings for item in listing["objects"]
               if any(term in item["key"].lower().removeprefix(listing["prefix"].lower()) for term in WANTED)]
    return {
        "schema_version": 1,
        "scope": "noaa-2013-merge-m2612-published-supplemental-prefix-access",
        "official_project": "https://www.fisheries.noaa.gov/inport/item/49649",
        "project_report": "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/2612/supplemental/ca2013_noaa_topobathy_merge_m2612_final_report.pdf",
        "listings": listings,
        "requested_accuracy_inventory_or_acoustic_assets_found": matches,
        "candidate_accuracy_layer_obtained": False,
        "candidate_acoustic_source_extent_obtained": False,
        "fishing_target": False,
        "limitations": [
            "These are two NOAA-published supplemental prefixes, not a complete search of NOAA archives or every possible delivery location.",
            "A filename match is a discovery lead only; it cannot qualify accuracy until its contents, footprint, units and source lineage are reviewed.",
            "The public 2013 DEM and COPC/LAS point distributions do not themselves supply the project-reported tiled vertical-accuracy layer or acoustic-source extent geodatabase.",
            "NOAA's source-reported RMSE and undefined cells are not conservative per-cell upper depth errors.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = audit()
    if args.verify and result != {key: value for key, value in json.loads(args.verify.read_text()).items() if key != "checked_at"}:
        raise SystemExit("NOAA 2013 supplemental asset access changed; review before promotion")
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"supplemental_prefixes": len(result["listings"]),
                      "objects": sum(len(row["objects"]) for row in result["listings"]),
                      "matching_assets": len(result["requested_accuracy_inventory_or_acoustic_assets_found"])}))


if __name__ == "__main__":
    main()

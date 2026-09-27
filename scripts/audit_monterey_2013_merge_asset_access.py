#!/usr/bin/env python3
"""Check NOAA's public 2612 distribution for missing merge inputs.

This is a bounded *availability* audit. A missing filename in this distribution
does not prove the NOAA accuracy/source-inventory deliverables do not exist.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BUCKET = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/"
PREFIXES = ("laz/geoid18/2612/supplemental/", "laz/geoid12a/2612/supplemental/")
FULL_PREFIX = "laz/geoid18/2612/"
WANTED = ("accuracy", "inventory", "source", "acoustic", ".gdb", ".fgdb")
OUTPUT = ROOT / "dist/data/monterey-2013-merge-public-asset-access.json"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


def parse_page(data, prefix):
    root = ET.fromstring(data)
    if root.tag != "{http://s3.amazonaws.com/doc/2006-03-01/}ListBucketResult":
        raise ValueError("NOAA listing response is not S3 ListBucketResult")
    if root.findtext("s:Prefix", namespaces=NS) != prefix:
        raise ValueError("NOAA listing prefix changed")
    truncated = root.findtext("s:IsTruncated", namespaces=NS)
    if truncated not in ("true", "false"):
        raise ValueError("NOAA listing truncation status missing")
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
    token = root.findtext("s:NextContinuationToken", namespaces=NS)
    if truncated == "true" and not token:
        raise ValueError("NOAA listing continuation token missing")
    return sorted(rows, key=lambda item: item["key"]), token


def parse_listing(data, prefix):
    rows, token = parse_page(data, prefix)
    if token:
        raise ValueError("NOAA supplemental listing needs pagination")
    return rows


def scan_full_archive(fetch):
    token = None
    rows = []
    pages = 0
    while pages < 25:
        query = {"list-type": "2", "prefix": FULL_PREFIX, "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        data = fetch(BUCKET + "?" + urlencode(query))
        if len(data) > 1_000_000:
            raise ValueError("NOAA full listing page exceeded review bound")
        page, token = parse_page(data, FULL_PREFIX)
        pages += 1
        rows.extend(page)
        if len(rows) > 20_000:
            raise ValueError("NOAA full archive exceeded review bound")
        if not token:
            break
    if token:
        raise ValueError("NOAA full archive listing exceeded 25 pages")
    if len({item["key"] for item in rows}) != len(rows):
        raise ValueError("NOAA full archive listing repeated keys")
    rows.sort(key=lambda item: item["key"])
    matches = [item["key"] for item in rows
               if any(term in item["key"].removeprefix(FULL_PREFIX).lower() for term in WANTED)]
    digest = hashlib.sha256()
    for item in rows:
        digest.update(f'{item["key"]}\t{item["bytes"]}\t{item["last_modified"]}\n'.encode())
    return {
        "prefix": FULL_PREFIX,
        "pages": pages,
        "objects": len(rows),
        "copc_laz_objects": sum(item["key"].endswith(".copc.laz") for item in rows),
        "stac_json_objects": sum(item["key"].startswith(FULL_PREFIX + "stac/") and item["key"].endswith(".json") for item in rows),
        "other_object_keys": [item["key"] for item in rows
                              if not item["key"].endswith(".copc.laz")
                              and not (item["key"].startswith(FULL_PREFIX + "stac/") and item["key"].endswith(".json"))],
        "listing_sha256": digest.hexdigest(),
        "requested_accuracy_inventory_or_acoustic_assets_found": matches,
    }


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
    full_archive = scan_full_archive(fetch)
    return {
        "schema_version": 1,
        "scope": "noaa-2013-merge-m2612-public-distribution-access",
        "official_project": "https://www.fisheries.noaa.gov/inport/item/49649",
        "project_report": "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/2612/supplemental/ca2013_noaa_topobathy_merge_m2612_final_report.pdf",
        "listings": listings,
        "full_archive": full_archive,
        "requested_accuracy_inventory_or_acoustic_assets_found": sorted(set(matches + full_archive["requested_accuracy_inventory_or_acoustic_assets_found"])),
        "candidate_accuracy_layer_obtained": False,
        "candidate_acoustic_source_extent_obtained": False,
        "fishing_target": False,
        "limitations": [
            "The 2612 full Geoid18 public distribution and two published supplemental prefixes are inspected, not every NOAA archive or delivery location.",
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
                      "full_archive_objects": result["full_archive"]["objects"],
                      "matching_assets": len(result["requested_accuracy_inventory_or_acoustic_assets_found"])}))


if __name__ == "__main__":
    main()

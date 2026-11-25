#!/usr/bin/env python3
"""Compare retained C25 basemap tile samples with local C15 relief build evidence.

Run with the C25 receipt.json and C15 COVERAGE-INDEX.json. Output is local review
context; neither a tile index hit nor a valid relief cell proves surveyed extent.
"""

import argparse
import json
import re
from pathlib import Path


def by_region(rows):
    result = {}
    for row in rows:
        region = row["region"]
        if not isinstance(region, str) or not region or region in result:
            raise ValueError(f"invalid or duplicate region: {region!r}")
        result[region] = row
    return result


def samples(points):
    if not points:
        raise ValueError("no basemap samples")
    for site, observations in sorted(points.items()):
        for zoom, obs in sorted(observations.items(), key=lambda item: int(item[0])):
            tile, indexed = obs["tile"], obs["indexed"]
            if (not isinstance(tile, list) or len(tile) != 3 or any(type(n) is not int for n in tile)
                    or not 0 <= tile[0] <= 30 or zoom != str(tile[0])
                    or not all(0 <= n < 2 ** tile[0] for n in tile[1:]) or type(indexed) is not bool):
                raise ValueError(f"invalid basemap sample: {site}/{zoom}")
            yield {"site": site, "tile": tile, "indexed": indexed}


def local_build(row):
    coverage = row["coverage"]
    if coverage in {"not-built", "not-classified-here"}:
        return None
    envelope, cells = row["envelope_sha256"], row["valid_cells"]
    if (coverage not in {"terrain-only", "terrain+contours"}
            or not isinstance(envelope, str) or not re.fullmatch(r"[0-9a-f]{64}", envelope)
            or type(cells) is not int or cells <= 0):
        raise ValueError(f"invalid local relief build evidence: {row['region']}")
    return {"coverage": coverage, "envelope_sha256": envelope, "valid_cells": cells}


def compare(index_receipt, coverage_index):
    if index_receipt["schema"] != "sc-offline-c25/1":
        raise ValueError("expected sc-offline-c25/1 basemap receipt")
    basemaps = by_region(index_receipt["north_c"])
    builds = by_region(coverage_index["rows"])
    return [
        {"region": region,
         "basemap_samples": list(samples(row["basemap"]["index"]["points"])),
         "relief_build": local_build(builds[region]) if region in builds else None,
         "surveyed_extent": "not established"}
        for region, row in sorted(basemaps.items())
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("basemap_receipt", type=Path)
    parser.add_argument("coverage_index", type=Path)
    args = parser.parse_args()
    try:
        rows = compare(json.loads(args.basemap_receipt.read_bytes()), json.loads(args.coverage_index.read_bytes()))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.error(str(exc))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()

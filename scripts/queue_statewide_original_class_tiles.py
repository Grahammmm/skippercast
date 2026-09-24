"""Inventory fine NOAA source-tile leads for every reviewed original USGS class grid.

This inventory prioritizes source acquisition only; no fishing geometry is made.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.queue_nbs_original_class_tiles import queue


def build(audit, metadata, scheme, usgs_cache):
    if audit.get("scope") != "usgs-state-waters-doi-native-grid-audit":
        raise ValueError("Original DOI native audit required")
    sources = [row for row in audit["products"] if row.get("kind") == "seafloor_character"
               and row.get("status") == "ok"]
    if not sources:
        raise ValueError("No reviewed original USGS class grids")
    products = []
    for source in sorted(sources, key=lambda row: (row["release_id"], row["archive_sha256"])):
        item = queue(source["release_id"], audit, metadata, scheme, usgs_cache,
                     archive_sha256=source["archive_sha256"])
        leads = [row for row in item["ranked_tiles"] if row["class3_pixels_in_envelope"] > 0]
        products.append({"release_id": source["release_id"],
                         "original_archive_sha256": source["archive_sha256"],
                         "original_metadata_sha256": source["metadata_sha256"],
                         "positive_fine_tile_leads": len(leads),
                         "ranked_positive_tiles": leads})
    return {"schema_version": 1, "scope": "statewide-original-class-noaa-fine-tile-source-queue",
            "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "noaa_scheme_sha256": item["noaa_scheme_sha256"],
            "source_grids": len(products),
            "positive_source_tile_pairs": sum(row["positive_fine_tile_leads"] for row in products),
            "products": products, "fishing_target": False, "exportable": False,
            "limitations": ["Original class-3 pixels inside a NOAA tile envelope are acquisition leads only.",
                            "Product/tile pairs may share source cells, and no fine measured depth, legal area or fish presence is established by this inventory.",
                            "Every promising raster and contributor table must be fetched, hash-checked and screened cell by cell before considering a map layer."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=Path("var/usgs-doi-native-audit.json"))
    parser.add_argument("--metadata", type=Path, default=Path("var/usgs-doi-metadata.json"))
    parser.add_argument("--scheme", type=Path, default=Path("var/nbs-cache/modeling-tile-scheme.gpkg"))
    parser.add_argument("--usgs-cache", type=Path, default=Path("var/usgs-doi-native-cache"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(json.loads(args.audit.read_text()), json.loads(args.metadata.read_text()),
                   args.scheme, args.usgs_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["source_grids"], "reviewed grids;", result["positive_source_tile_pairs"],
          "source-tile leads; no fishing targets")


if __name__ == "__main__":
    main()

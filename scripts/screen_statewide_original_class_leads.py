"""Check original USGS class-3 cells against strict NOAA measured-depth cells statewide.

Only NOAA tiles with passing measured depth from the separate source triage are
opened. This source comparison never publishes fishing coordinates or scores.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.audit_nbs_modeling_tile import sha256
from scripts.screen_original_class_nbs_tiles import screen


def build(source_queue, depth_triage, native_audit, metadata, scheme, nbs_cache, usgs_cache):
    if source_queue.get("scope") != "statewide-original-class-noaa-fine-tile-source-queue" \
            or depth_triage.get("scope") != "statewide-original-class-noaa-measured-depth-triage":
        raise ValueError("Statewide source queue and measured-depth triage are required")
    scheme_digest = sha256(scheme)
    if source_queue["noaa_scheme_sha256"] != scheme_digest or depth_triage["noaa_scheme_sha256"] != scheme_digest:
        raise ValueError("NOAA source scheme changed")
    if native_audit.get("scope") != "usgs-state-waters-doi-native-grid-audit":
        raise ValueError("Original USGS DOI audit required")
    key = lambda row: (row["release_id"], row["original_archive_sha256"])
    triaged = {key(row): row for row in depth_triage["products"]}
    if set(triaged) != {key(row) for row in source_queue["products"]}:
        raise ValueError("Depth triage does not cover every original class grid")
    products = []
    for product in source_queue["products"]:
        reviewed = triaged[key(product)]
        leads = {row["tile"]: row for row in product["ranked_positive_tiles"]}
        if set(leads) != {row["tile"] for row in reviewed["tiles"]}:
            raise ValueError("Depth triage omits source tile leads")
        if product["positive_fine_tile_leads"] != len(leads) or any(
                row["original_class3_pixels_in_tile_envelope"] != leads[row["tile"]]["class3_pixels_in_envelope"]
                for row in reviewed["tiles"]):
            raise ValueError("Original source class counts changed since depth triage")
        positive = [row for row in reviewed["tiles"] if row["qualified_measured_depth_pixels"] > 0]
        checked = []
        if positive:
            single_queue = {"scope": "original-usgs-hard-class-noaa-tile-acquisition-queue",
                            "fishing_target": False, "release_id": product["release_id"],
                            "usgs_original_archive_sha256": product["original_archive_sha256"],
                            "usgs_original_metadata_sha256": product["original_metadata_sha256"],
                            "noaa_scheme_sha256": scheme_digest,
                            "ranked_tiles": [leads[row["tile"]] for row in positive]}
            receipts = [{"tile": row["tile"], "raster_sha256": row["noaa_raster_sha256"],
                         "rat_sha256": row["noaa_rat_sha256"], "scheme_sha256": scheme_digest}
                        for row in positive]
            checked = screen(single_queue, native_audit, metadata, scheme, nbs_cache,
                             usgs_cache, receipts)["tiles"]
            if any(row["qualified_measured_depth_pixels"] != next(
                    item["qualified_measured_depth_pixels"] for item in positive if item["tile"] == row["tile"])
                   for row in checked):
                raise ValueError("NOAA measured-depth qualification changed since triage")
        products.append({"release_id": product["release_id"],
                         "original_archive_sha256": product["original_archive_sha256"],
                         "positive_source_tile_leads": product["positive_fine_tile_leads"],
                         "tiles_with_qualified_measured_depth": len(positive),
                         "strict_original_class3_measured_depth_overlap_cells": sum(
                             row["strict_measured_class3_overlap_pixels"] for row in checked),
                         "tiles": checked})
    return {"schema_version": 1, "scope": "statewide-original-class-noaa-measured-cell-overlap-review",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "noaa_scheme_sha256": scheme_digest,
            "original_class_grids": len(products),
            "source_tile_pairs_with_qualified_depth": sum(row["tiles_with_qualified_measured_depth"] for row in products),
            "tile_level_overlap_cells": sum(row["strict_original_class3_measured_depth_overlap_cells"] for row in products),
            "products": products, "fishing_target": False, "exportable": False,
            "limitations": ["USGS class and NOAA depth are historical, differently acquired sources; cells are not independent fish observations.",
                            "Counts may overlap across tiles and original USGS products; no coastwide unique area is claimed.",
                            "A nonzero class/depth overlap still requires original survey hazard reports, current ENC, MPA and method-specific legal review, approach routes, species evidence and position uncertainty before any target or export."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--triage", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=Path("var/usgs-doi-native-audit.json"))
    parser.add_argument("--metadata", type=Path, default=Path("var/usgs-doi-metadata.json"))
    parser.add_argument("--scheme", type=Path, default=Path("var/nbs-cache/modeling-tile-scheme.gpkg"))
    parser.add_argument("--nbs-cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--usgs-cache", type=Path, default=Path("var/usgs-doi-native-cache"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(json.loads(args.queue.read_text()), json.loads(args.triage.read_text()),
                   json.loads(args.audit.read_text()), json.loads(args.metadata.read_text()),
                   args.scheme, args.nbs_cache, args.usgs_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["source_tile_pairs_with_qualified_depth"], "source-tile pairs cross-screened;",
          result["tile_level_overlap_cells"], "historical tile-level overlap cells; no fishing targets")


if __name__ == "__main__":
    main()

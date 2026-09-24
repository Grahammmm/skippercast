"""Check exact NOAA source rasters for selected USGS class-grid acquisition leads.

If a tile has passing measured-depth cells, an exact class/depth intersection
and legal/hazard review must follow. This queue never creates fishing spots.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.audit_nbs_modeling_tile import audit, sha256


def triage(source_queue, scheme, cache, release_ids, *, fetch=False):
    if source_queue.get("scope") != "statewide-original-class-noaa-fine-tile-source-queue" \
            or source_queue.get("fishing_target") is not False:
        raise ValueError("Reviewed statewide source queue required")
    if source_queue["noaa_scheme_sha256"] != sha256(scheme):
        raise ValueError("NOAA tile scheme changed")
    if not release_ids:
        raise ValueError("Select at least one USGS release")
    products = [row for row in source_queue["products"] if row["release_id"] in release_ids]
    if set(release_ids) != {row["release_id"] for row in products}:
        raise ValueError("Requested USGS release missing from source queue")
    tiles = {lead["tile"] for row in products for lead in row["ranked_positive_tiles"]}
    checked = {tile: audit(scheme, tile, cache, fetch=fetch) for tile in sorted(tiles)}
    results = []
    for product in products:
        results.append({"release_id": product["release_id"],
                        "original_archive_sha256": product["original_archive_sha256"],
                        "positive_fine_tile_leads": product["positive_fine_tile_leads"],
                        "tiles": [{"tile": lead["tile"],
                                   "original_class3_pixels_in_tile_envelope": lead["class3_pixels_in_envelope"],
                                   "noaa_raster_sha256": checked[lead["tile"]]["raster_sha256"],
                                   "noaa_rat_sha256": checked[lead["tile"]]["rat_sha256"],
                                   "qualified_measured_depth_pixels": checked[lead["tile"]]["counts"]["qualified_screen_pixels"],
                                   "needs_exact_class_depth_overlap": checked[lead["tile"]]["counts"]["qualified_screen_pixels"] > 0}
                                  for lead in product["ranked_positive_tiles"]]})
    return {"schema_version": 1, "scope": "statewide-original-class-noaa-measured-depth-triage",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "noaa_scheme_sha256": sha256(scheme), "release_ids": sorted(set(release_ids)),
            "unique_noaa_tiles_checked": len(checked), "products": results,
            "all_checked_tiles_have_zero_qualified_depth": all(
                row["counts"]["qualified_screen_pixels"] == 0 for row in checked.values()),
            "fishing_target": False, "exportable": False,
            "limitations": ["An original USGS class-3 tile-envelope count is not a class/depth overlap.",
                            "NOAA NBS Modeling is a test-and-evaluation compilation, not a navigation chart.",
                            "Passing depth cells would still need exact source-class, current closure, hazard, chart, species and local rule review before map promotion."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--release-id", action="append", required=True)
    parser.add_argument("--scheme", type=Path, default=Path("var/nbs-cache/modeling-tile-scheme.gpkg"))
    parser.add_argument("--cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = triage(json.loads(args.queue.read_text()), args.scheme, args.cache,
                    args.release_id, fetch=args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["unique_noaa_tiles_checked"], "exact NOAA tiles checked;",
          "all zero strict measured-depth" if result["all_checked_tiles_have_zero_qualified_depth"]
          else "exact class/depth overlap still required")


if __name__ == "__main__":
    main()

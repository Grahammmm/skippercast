"""Cross-check audited USGS class cells against audited NOAA measured MLLW cells.

This is a research receipt, never a waypoint, legal clearance or fish score.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from scripts.audit_nbs_modeling_tile import audit, contributors, qualified_mask, sha256
from scripts.qualify_regular_bag_hard import original_character


def screen(queue, native_audit, metadata, scheme, nbs_cache, usgs_cache, tile_receipts):
    if queue.get("scope") != "original-usgs-hard-class-noaa-tile-acquisition-queue" or queue.get("fishing_target") is not False:
        raise ValueError("Source-only tile queue required")
    if native_audit.get("scope") != "usgs-state-waters-doi-native-grid-audit":
        raise ValueError("Original USGS DOI native audit required")
    if queue["noaa_scheme_sha256"] != sha256(scheme):
        raise ValueError("NOAA tile scheme changed")
    release_id = queue["release_id"]
    rows = [row for row in native_audit["products"] if row.get("release_id") == release_id
            and row.get("kind") == "seafloor_character" and row.get("status") == "ok"
            and row.get("archive_sha256") == queue["usgs_original_archive_sha256"]]
    if len(rows) != 1 or rows[0]["archive_sha256"] != queue["usgs_original_archive_sha256"] \
            or rows[0]["metadata_sha256"] != queue["usgs_original_metadata_sha256"]:
        raise ValueError("Original USGS source or metadata changed")
    source_uri = original_character(rows[0], usgs_cache, metadata)
    queued = {row["tile"]: row for row in queue["ranked_tiles"]}
    results = []
    with rasterio.open(source_uri) as original:
        if original.count != 1 or not original.crs or not all(1.5 <= x <= 5.1 for x in original.res):
            raise ValueError("Unsupported original class grid")
        for receipt in tile_receipts:
            tile = receipt["tile"]
            if tile not in queued or queued[tile]["class3_pixels_in_envelope"] <= 0:
                raise ValueError("Tile is not a positive source lead: " + tile)
            checked = audit(scheme, tile, nbs_cache)
            if any(checked[key] != receipt[key] for key in ("raster_sha256", "rat_sha256", "scheme_sha256")):
                raise ValueError("NOAA raster or RAT changed: " + tile)
            source_rows = contributors(nbs_cache / f"{tile}.tiff.aux.xml")
            with rasterio.open(nbs_cache / f"{tile}.tiff") as raster:
                elevation, uncertainty, contributor = raster.read()
                qualified = qualified_mask(elevation, uncertainty, contributor, source_rows,
                                           resolution_m=max(raster.res))
                with WarpedVRT(original, crs=raster.crs, transform=raster.transform,
                               width=raster.width, height=raster.height,
                               resampling=Resampling.nearest,
                               nodata=original.nodata) as aligned:
                    class_grid = aligned.read(1, masked=True)
                hard = ~np.ma.getmaskarray(class_grid) & (class_grid.data == 3)
                overlap = qualified & hard
                ids, counts = np.unique(contributor[overlap], return_counts=True)
                results.append({"tile": tile, "noaa_raster_sha256": receipt["raster_sha256"],
                                "noaa_rat_sha256": receipt["rat_sha256"],
                                "qualified_measured_depth_pixels": int(qualified.sum()),
                                "original_class3_pixels_at_noaa_cell_centers": int(hard.sum()),
                                "strict_measured_class3_overlap_pixels": int(overlap.sum()),
                                "source_survey_contributors": [
                                    {"source_survey_id": source_rows[int(ident)]["source_survey_id"],
                                     "survey_date_end": source_rows[int(ident)]["survey_date_end"],
                                     "overlap_pixels": int(count)} for ident, count in zip(ids, counts)]})
    return {"schema_version": 1, "scope": "original-usgs-class3-noaa-measured-depth-screen",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "release_id": release_id, "usgs_original_archive_sha256": rows[0]["archive_sha256"],
            "noaa_scheme_sha256": sha256(scheme), "tiles": results,
            "fishing_target": False, "exportable": False,
            "limitations": ["Historical class-3 habitat is nearest-neighbor sampled at NOAA cell centers; sources differ in age and survey method.",
                            "Counts are source cells, not unique fishable area or confirmed rock piles.",
                            "This screen does not establish legal access, hazards, current chart depth, safe routes, species presence or catch quality."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=Path("var/usgs-doi-native-audit.json"))
    parser.add_argument("--metadata", type=Path, default=Path("var/usgs-doi-metadata.json"))
    parser.add_argument("--scheme", type=Path, default=Path("var/nbs-cache/modeling-tile-scheme.gpkg"))
    parser.add_argument("--nbs-cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--usgs-cache", type=Path, default=Path("var/usgs-doi-native-cache"))
    parser.add_argument("--tile-receipt", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = screen(json.loads(args.queue.read_text()), json.loads(args.audit.read_text()),
                    json.loads(args.metadata.read_text()), args.scheme, args.nbs_cache, args.usgs_cache,
                    [json.loads(path.read_text()) for path in args.tile_receipt])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(sum(row["strict_measured_class3_overlap_pixels"] for row in result["tiles"]),
          "tile-level research overlap cells; no fishing targets")


if __name__ == "__main__":
    main()

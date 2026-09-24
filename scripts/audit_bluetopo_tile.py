"""Audit an exact NOAA BlueTopo tile as a research-only depth source lead.

BlueTopo uses NAVD88, not chart MLLW. No pixel here is converted into a
fishing depth, waypoint, safe route, or verified bottom type.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import numpy as np
import rasterio

from scripts.audit_nbs_modeling_tile import contributors, is_measured_survey, item_year, sha256, verified_file


def scheme_row(scheme, tile):
    with sqlite3.connect(scheme) as db:
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or not table[0].startswith("BlueTopo_Tile_Scheme_"):
            raise ValueError("Not an official BlueTopo tile scheme")
        db.row_factory = sqlite3.Row
        row = db.execute(f'SELECT * FROM "{table[0]}" WHERE tile=?', (tile,)).fetchone()
        if row is None or not row["GeoTIFF_Link"] or not row["RAT_Link"]:
            raise ValueError(f"BlueTopo tile {tile} has no published raster and RAT")
        return dict(row)


def audit(scheme, tile, cache, *, fetch=False, min_survey_year=1990):
    row = scheme_row(scheme, tile)
    raster_path = cache / f"{tile}.tiff"
    rat_path = cache / f"{tile}.tiff.aux.xml"
    raster_hash = verified_file(row["GeoTIFF_Link"], row["GeoTIFF_SHA256_Checksum"], raster_path, fetch)
    rat_hash = verified_file(row["RAT_Link"], row["RAT_SHA256_Checksum"], rat_path, fetch)
    sources = contributors(rat_path)
    with rasterio.open(raster_path) as raster:
        if raster.descriptions != ("Elevation", "Uncertainty", "Contributor"):
            raise ValueError("BlueTopo bands changed")
        if "navd88" not in raster.crs.to_wkt().lower():
            raise ValueError("BlueTopo vertical datum is not NAVD88")
        elevation, uncertainty, contributor = raster.read()
        observed = set(np.unique(contributor[np.isfinite(contributor)]).astype(int))
        if observed - set(sources):
            raise ValueError("BlueTopo RAT does not identify all contributor codes")
        measured = {key for key, value in sources.items() if is_measured_survey(value)}
        recent = {key for key in measured if item_year(sources[key]["survey_date_end"]) >= min_survey_year}
        valid = np.isfinite(elevation) & np.isfinite(uncertainty)
        measured_mask = valid & np.isin(contributor, list(measured))
        recent_mask = valid & np.isin(contributor, list(recent))
        below_navd88 = valid & (elevation < 0)
        recent_below = recent_mask & below_navd88
        recent_counts = Counter(int(x) for x in contributor[recent_below])
        counts = {"finite_elevation_and_uncertainty_pixels": int(valid.sum()),
                  "measured_contributor_pixels": int(measured_mask.sum()),
                  "measured_since_min_year_pixels": int(recent_mask.sum()),
                  "measured_since_min_year_below_navd88_pixels": int(recent_below.sum()),
                  "measured_since_min_year_below_navd88_uncertainty_le_1m_pixels": int((recent_below & (uncertainty <= 1)).sum())}
        bounds = [raster.bounds.left, raster.bounds.bottom, raster.bounds.right, raster.bounds.top]
        crs = raster.crs.to_wkt()
        resolution = list(raster.res)
    return {"schema_version": 1, "scope": "bluetopo-single-tile-source-review",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tile": tile, "scheme_sha256": sha256(scheme), "delivered_date": row["Delivered_Date"],
            "raster_url": row["GeoTIFF_Link"], "raster_sha256": raster_hash,
            "rat_url": row["RAT_Link"], "rat_sha256": rat_hash,
            "vertical_datum": "NAVD88", "raster_crs_wkt": crs, "bounds_native_crs": bounds,
            "resolution_m": resolution, "min_survey_year": min_survey_year,
            "counts": counts,
            "recent_measured_contributors": [
                {"source_survey_id": sources[key]["source_survey_id"],
                 "survey_date_end": sources[key]["survey_date_end"], "below_navd88_pixels": count,
                 "license_name": sources[key].get("license_name")}
                for key, count in sorted(recent_counts.items())],
            "fishing_target": False, "exportable": False,
            "limitations": ["Negative NAVD88 elevation does not prove submerged fishing depth; NAVD88 is not MLLW and this review does not convert datums.",
                            "A measured contributor flag is a source lead, not independent substrate or fish evidence.",
                            "BlueTopo may reuse surveys already counted in NOAA BAG or NBS Modeling reviews.",
                            "This product is not for navigation; hazards, protected areas, local rules and original survey reports remain unreviewed for this tile."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheme", type=Path, required=True)
    parser.add_argument("--tile", required=True)
    parser.add_argument("--cache", type=Path, default=Path("var/bluetopo-cache"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.scheme, args.tile, args.cache, fetch=args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(args.tile, result["counts"])


if __name__ == "__main__":
    main()

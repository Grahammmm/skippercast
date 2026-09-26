"""Screen one exact NOAA NBS Modeling tile; never promote it to a fishing spot.

The scheme supplies source URLs and checksums. Its footprint does not establish
measured bathymetry. The raster contributor RAT is checked pixel by pixel.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.request import urlopen
import xml.etree.ElementTree as ET

import numpy as np
import rasterio
from skippercast.platform.bottom_targets import cells_qualified


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scheme_row(scheme, tile):
    with sqlite3.connect(scheme) as db:
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or not table[0].startswith("Modeling_Tile_Scheme_"):
            raise ValueError("Not an NBS Modeling tile scheme")
        name = table[0]
        db.row_factory = sqlite3.Row
        row = db.execute(f'SELECT * FROM "{name}" WHERE tile=?', (tile,)).fetchone()
        if row is None or not row["GeoTIFF_Link"] or not row["RAT_Link"]:
            raise ValueError(f"Tile {tile} has no published raster and RAT")
        return dict(row)


def verified_file(url, expected, destination, fetch, *, max_bytes=128 * 1024 * 1024):
    if not destination.exists():
        if not fetch:
            raise FileNotFoundError(destination)
        if not url.startswith("https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/"):
            raise ValueError("Unexpected NBS file host")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > max_bytes:
                    raise ValueError(f"NBS file exceeds {max_bytes} byte limit")
                size = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"NBS file exceeds {max_bytes} byte limit")
                    output.write(chunk)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(destination)
    actual = sha256(destination)
    if actual.lower() != expected.lower():
        raise ValueError(f"SHA-256 mismatch for {destination}")
    return actual


def contributors(rat_path):
    root = ET.parse(rat_path).getroot()
    fields = [node.findtext("Name") for node in root.findall(".//FieldDefn")]
    if not {"value", "coverage", "bathy_coverage", "source_survey_id", "survey_date_end"} <= set(fields):
        raise ValueError("Contributor RAT lacks required provenance fields")
    return {int(row["value"]): row for row in (
        dict(zip(fields, [cell.text for cell in node.findall("F")]))
        for node in root.findall(".//Row"))}


def is_measured_survey(item):
    source = item["source_survey_id"].lower()
    return (item["coverage"] == "1" and item["bathy_coverage"] == "1"
            and ".interpolated" not in source and "chart" not in source
            and "generalization" not in source)


def qualified_mask(elevation, uncertainty, contributor, source_rows, *, max_uncertainty_m=1.0,
                   min_survey_year=1990, resolution_m=4.0, limit_ft=200):
    recent = {value for value, item in source_rows.items()
              if is_measured_survey(item) and item_year(item["survey_date_end"]) >= min_survey_year}
    return (cells_qualified(elevation, uncertainty, resolution_m,
                            maximum_uncertainty_m=max_uncertainty_m, limit_ft=limit_ft)
            & np.isin(contributor, list(recent)))


def audit(scheme, tile, cache, *, fetch=False, max_uncertainty_m=1.0, min_survey_year=1990,
          limit_ft=200):
    if limit_ft not in (200, 300):
        raise ValueError('Only reviewed 200- or 300-foot planning limits are supported')
    row = scheme_row(scheme, tile)
    raster_path = cache / f"{tile}.tiff"
    rat_path = cache / f"{tile}.tiff.aux.xml"
    raster_digest = verified_file(row["GeoTIFF_Link"], row["GeoTIFF_SHA256_Checksum"], raster_path, fetch)
    rat_digest = verified_file(row["RAT_Link"], row["RAT_SHA256_Checksum"], rat_path, fetch)
    source_rows = contributors(rat_path)
    with rasterio.open(raster_path) as raster:
        if raster.descriptions != ("Elevation", "Uncertainty", "Contributor"):
            raise ValueError("Unexpected NBS raster bands")
        if "MLLW" not in raster.crs.to_wkt():
            raise ValueError("Vertical datum is not explicitly MLLW")
        elevation, uncertainty, contributor = raster.read()
        unlisted = set(np.unique(contributor[np.isfinite(contributor)]).astype(int)) - set(source_rows)
        if unlisted:
            raise ValueError(f"Contributor RAT is missing raster values: {sorted(unlisted)[:5]}")
        depth = np.isfinite(elevation) & (elevation <= -25 / 3.28084) & (elevation >= -limit_ft / 3.28084)
        measured = {value for value, item in source_rows.items()
                    if is_measured_survey(item)}
        recent = {value for value in measured
                  if item_year(source_rows[value]["survey_date_end"]) >= min_survey_year}
        qualified = qualified_mask(elevation, uncertainty, contributor, source_rows,
                                   max_uncertainty_m=max_uncertainty_m,
                                   min_survey_year=min_survey_year, resolution_m=max(raster.res),
                                   limit_ft=limit_ft)
        counts = {f"depth_25_to_{limit_ft}_ft_pixels": int(depth.sum()),
                  "measured_depth_pixels": int((depth & np.isin(contributor, list(measured))).sum()),
                  "recent_measured_depth_pixels": int((depth & np.isin(contributor, list(recent))).sum()),
                  "qualified_screen_pixels": int(qualified.sum())}
        contributing = Counter(int(v) for v in contributor[qualified])
        crs = raster.crs.to_wkt()
        resolution = list(raster.res)
    return {"schema_version": 1, "scope": "nbs-modeling-single-tile-source-screen",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tile": tile, "scheme_sha256": sha256(scheme), "delivered_date": row["Delivered_Date"],
            "raster_url": row["GeoTIFF_Link"], "raster_sha256": raster_digest,
            "rat_url": row["RAT_Link"], "rat_sha256": rat_digest,
            "vertical_datum": "MLLW", "raster_crs_wkt": crs, "resolution_m": resolution,
            "screen": {"depth_ft": [25, limit_ft], "max_uncertainty_m": max_uncertainty_m,
                       "min_survey_year": min_survey_year, "planning_depth_margin_m": 2,
                       "measured_contributor_flags_required": True},
            "counts": counts,
            "qualified_contributors": [{"survey_id": source_rows[value]["source_survey_id"],
                                         "survey_date_end": source_rows[value]["survey_date_end"],
                                         "pixels": count} for value, count in sorted(contributing.items())],
            "test_and_evaluation_product": True, "fishing_target": False, "exportable": False,
            "caveats": ["NBS Modeling is a test-and-evaluation product, not a navigation chart.",
                        "Tile footprints do not establish measured coverage; interpolation and old soundings fail this screen.",
                        "Screened pixels are source leads only; substrate, hazards, protected areas, access and species rules require separate review."]}


def item_year(value):
    try:
        return int(value[:4])
    except (ValueError, TypeError):
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheme", type=Path, required=True)
    parser.add_argument("--tile", required=True)
    parser.add_argument("--cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--limit-ft", type=int, choices=(200, 300), default=200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.scheme, args.tile, args.cache, fetch=args.fetch, limit_ft=args.limit_ft)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(args.tile, result["counts"])


if __name__ == "__main__":
    main()

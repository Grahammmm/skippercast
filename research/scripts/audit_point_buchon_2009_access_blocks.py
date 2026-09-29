"""Screen private 2009 CSUMB / 2008 USGS research blocks against fresh GIS.

This is a whole-block partial MPA/federal/ENC triage. It does not certify a
chart depth, full boat route, open fishing season or safe approach.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.warp import Resampling, reproject
from shapely.geometry import box, mapping

from research.scripts.audit_point_buchon_2009_csumb_products import (
    ARCHIVE_SHA256, GRIDS, extract_grids, sha256_file,
)
from research.scripts.audit_point_buchon_original_pair import EXPECTED_CLASS, original_tiff
from research.scripts.audit_point_buchon_rov_access_blocks import (
    MARGIN_M, closures, feature_fingerprint,
)


ROOT = Path(__file__).resolve().parents[2]
GRID_M = 100
EXPECTED_CELLS = 87257
EXPECTED_BLOCKS = 181


def source_blocks(archive, class_zip):
    blocks = defaultdict(lambda: Counter())
    if sha256_file(archive) != ARCHIVE_SHA256 or sha256_file(class_zip) != EXPECTED_CLASS:
        raise ValueError("Original CSUMB or USGS source bytes changed")
    with tempfile.TemporaryDirectory() as temp:
        extract_grids(archive, Path(temp))
        with rasterio.open(original_tiff(class_zip)) as character:
            source = character.read(1)
            to_usgs = Transformer.from_crs("EPSG:26910", "EPSG:32610", always_xy=True)
            for name, spacing, minimum_m, maximum_m in GRIDS:
                with rasterio.open(Path(temp) / "ArcViewGrids" / name) as depth:
                    if (str(depth.crs) != "EPSG:26910" or depth.res != (spacing, spacing)
                            or str(character.crs) != "EPSG:32610"):
                        raise ValueError("Original grid CRS or spacing changed")
                    classes = np.zeros(depth.shape, dtype="uint8")
                    reproject(source, classes, src_transform=character.transform,
                              src_crs=character.crs, src_nodata=character.nodata,
                              dst_transform=depth.transform, dst_crs=depth.crs,
                              dst_nodata=0, resampling=Resampling.nearest)
                    values = depth.read(1, masked=True)
                    metres = -values.data
                    for lower_ft, upper_ft in ((200, 250), (250, 300)):
                        lo = max(minimum_m, lower_ft * .3048)
                        hi = min(maximum_m, upper_ft * .3048)
                        rows, cols = np.where((~np.ma.getmaskarray(values))
                                              & (metres >= lo) & (metres < hi)
                                              & (classes == 3))
                        x = depth.transform.c + (cols + .5) * depth.transform.a
                        y = depth.transform.f + (rows + .5) * depth.transform.e
                        x, y = to_usgs.transform(x, y)
                        bins = np.column_stack((np.floor(x / GRID_M).astype("i4"),
                                                np.floor(y / GRID_M).astype("i4")))
                        unique, counts = np.unique(bins, axis=0, return_counts=True)
                        key = f"{lower_ft}-{upper_ft}ft_{spacing}m"
                        for location, count in zip(map(tuple, unique), counts):
                            blocks[location][key] += int(count)
    if len(blocks) != EXPECTED_BLOCKS or sum(sum(row.values()) for row in blocks.values()) != EXPECTED_CELLS:
        raise ValueError("Original independent depth/class block index changed")
    return blocks


def build(blocks, mpas, federal, enc, *, now=None):
    now = now or datetime.now(timezone.utc)
    cdfw_coverage, enc_coverage, mpa, gea, danger, gea_count = closures(
        mpas, federal, enc, now)
    totals = Counter()
    private = []
    for (east, north), cell_counts in sorted(blocks.items()):
        footprint = box(east * GRID_M, north * GRID_M,
                        (east + 1) * GRID_M, (north + 1) * GRID_M)
        margin = footprint.buffer(MARGIN_M)
        if not cdfw_coverage.covers(margin) or not enc_coverage.covers(margin):
            raise ValueError("Official Point Buchon GIS query does not cover full research margin")
        holds = {"mpa": margin.intersects(mpa), "gea": margin.intersects(gea),
                 "charted_danger": not danger.is_empty and margin.intersects(danger)}
        area_m2 = sum(count * (2 if key.endswith("_2m") else 5) ** 2
                      for key, count in cell_counts.items())
        totals["blocks"] += 1
        totals["nominal_hard_rugose_cell_area_m2"] += area_m2
        for key, count in cell_counts.items():
            totals[key + "_cells"] += count
        for key, held in holds.items():
            totals[key + "_margin_blocks"] += int(held)
            totals[key + "_margin_hard_cell_area_m2"] += area_m2 if held else 0
        totals["all_three_clear_margin_blocks"] += int(not any(holds.values()))
        totals["all_three_clear_margin_hard_cell_area_m2"] += area_m2 if not any(holds.values()) else 0
        private.append({"type": "Feature", "geometry": mapping(footprint),
                        "properties": {"nominal_source_datum_cell_counts": dict(cell_counts),
                                       "nominal_hard_cell_area_m2": area_m2,
                                       "research_margin_m": MARGIN_M,
                                       "review_holds": holds,
                                       "fishing_target": False, "exportable": False}})
    return ({"schema_version": 1,
             "scope": "point-buchon-2009-csumb-original-100m-access-triage",
             "research_grid_m": GRID_M, "review_margin_m": MARGIN_M,
             "source_vertical_datum": "NAVD88 Geoid03, not chart-qualified MLLW",
             "cdfw_mpa_feature_count": len(mpas["features"]),
             "noaa_gea_feature_count": gea_count,
             "noaa_enc_danger_feature_count": len(enc["features"]),
             "noaa_enc_query_layers": len(enc["query_receipts"]),
             "source_checked_at": {"cdfw_mpa": mpas["checked_at"],
                                   "noaa_federal": federal["retrieved_at"],
                                   "noaa_enc": enc["checked_at"]},
             "source_urls": {"cdfw_mpa": mpas["source_url"],
                             "noaa_federal": federal["service_url"],
                             "noaa_enc": enc["source_url"]},
             "official_geometry_sha256": {
                 "cdfw_mpas": feature_fingerprint(mpas["features"]),
                 "noaa_federal_geas": feature_fingerprint(
                     [row for row in federal["features"] if row["properties"]["area_type"] == "GEA"]),
                 "noaa_enc_dangers": feature_fingerprint(enc["features"]),
             },
             "totals": dict(sorted(totals.items())),
             "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
             "limitations": [
                 "Each 100 m block is a research bin of 2009 measured source-datum depth and nominally overlaid 2008 hard/rugose class, not an exact rock outline.",
                 "The 100 m margin is a conservative GIS triage radius, not a validated positioning, drift or safe-transit buffer.",
                 "CDFW MPA, NOAA GEA and 18 ENC danger-layer queries are partial screens. Security areas, all chart features, current species rules, full approach/drift/return routes and actual boat conditions remain unchecked.",
                 "NAVD88-to-MLLW per-cell conversion, upper product TPU, cross-survey registration and public reuse rights remain unresolved. A clear partial screen is not fishing permission or a rank.",
             ]},
            {"type": "FeatureCollection", "crs": "EPSG:32610",
             "scope": "private-point-buchon-2009-csumb-100m-research-blocks",
             "features": private})


def stable(report):
    return {k: v for k, v in report.items()
            if k not in ("source_checked_at", "input_sha256")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "var/review/point-buchon-additional-products/Pt_Buchon_control_additional_products.tar.gz")
    parser.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip")
    parser.add_argument("--mpas", type=Path, required=True)
    parser.add_argument("--federal", type=Path, required=True)
    parser.add_argument("--enc", type=Path, required=True)
    parser.add_argument("--private-blocks", type=Path, default=ROOT / "var/review/point-buchon-2009-csumb-100m-blocks.geojson")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-2009-csumb-access-triage.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    blocks = source_blocks(args.archive, args.character)
    source_paths = {"archive": args.archive, "character": args.character,
                    "mpas": args.mpas, "federal": args.federal, "enc": args.enc}
    report, private = build(blocks, *(json.loads(path.read_text())
                                      for path in (args.mpas, args.federal, args.enc)))
    report["input_sha256"] = {key: sha256_file(path) for key, path in source_paths.items()}
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise ValueError("Point Buchon original-cell access result changed; review before publication")
    args.private_blocks.parent.mkdir(parents=True, exist_ok=True)
    args.private_blocks.write_text(json.dumps(private, separators=(",", ":")) + "\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["totals"])


if __name__ == "__main__":
    main()

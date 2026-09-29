#!/usr/bin/env python3
"""Join historical open-reference ROV observations to original Point Buchon cells.

Only aggregate research counts leave this process. The original products have
unresolved chart datum, upper error, source acquisition year and registration.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from pyproj import Transformer
import rasterio
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from research.scripts.audit_point_buchon_2009_csumb_products import (
    ARCHIVE_SHA256, GRIDS, extract_grids, sha256_file,
)
from research.scripts.audit_point_buchon_original_pair import (
    EXPECTED_CLASS, original_tiff, published_character_accuracy,
)
from research.scripts.build_central_rov_depth_evidence import fetch, source_bytes


ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "catalog/central-rov-2024-source.json"
ARCHIVE = ROOT / "var/review/point-buchon-additional-products/Pt_Buchon_control_additional_products.tar.gz"
CHARACTER = ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip"
CHARACTER_METADATA = ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon_metadata.xml"
ROV = ROOT / "var/review/rov-zenodo-10929417.csv"
BLOCKS = ROOT / "var/review/point-buchon-2009-csumb-100m-blocks.geojson"
ACCESS = ROOT / "dist/data/point-buchon-2009-csumb-access-triage.json"
ROCKFISH = ("Copper_rf", "Gopher_rf", "Vermilion_rf", "Canary_rf",
            "Quillback_rf", "Yelloweye_rf", "Brown_rf")
MARGINS = (0, 10, 25)
LOWER_M, UPPER_M = 60.96, 91.44


def checked_blocks(path: Path):
    data = json.loads(path.read_text())
    if data.get("crs") != "EPSG:32610" or len(data.get("features", [])) != 181:
        raise ValueError("Private Point Buchon research block frame changed")
    features = data["features"]
    if any(f["properties"].get("fishing_target") is not False
           or f["properties"].get("exportable") is not False for f in features):
        raise ValueError("Research-only block release gate changed")
    return features, [shape(f["geometry"]) for f in features]


def source_depth_at(point, shallow, deep):
    shallow_value = next(shallow.sample([point], masked=True))[0]
    deep_value = next(deep.sample([point], masked=True))[0]
    d2 = None if np.ma.is_masked(shallow_value) else -float(shallow_value)
    d5 = None if np.ma.is_masked(deep_value) else -float(deep_value)
    if d2 is not None and LOWER_M <= d2 < 85:
        return d2, 2
    if d5 is not None and 85 <= d5 <= UPPER_M:
        return d5, 5
    return None, None


def build(rov_path: Path = ROV, archive: Path = ARCHIVE,
          character: Path = CHARACTER, block_path: Path = BLOCKS,
          access_path: Path = ACCESS, character_metadata: Path = CHARACTER_METADATA) -> dict:
    pin = json.loads(PIN.read_text())
    source_bytes(rov_path, pin)
    if sha256_file(archive) != ARCHIVE_SHA256 or sha256_file(character) != EXPECTED_CLASS:
        raise ValueError("Original Point Buchon depth or character changed")
    class_accuracy = published_character_accuracy(character_metadata)
    access = json.loads(access_path.read_text())
    if (access.get("scope") != "point-buchon-2009-csumb-original-100m-access-triage"
            or access.get("totals", {}).get("blocks") != 181
            or access.get("qualified_waypoints") != 0
            or access.get("fishing_target") is not False):
        raise ValueError("Point Buchon partial access screen changed")
    features, geometries = checked_blocks(block_path)
    tree = STRtree(geometries)
    to_depth = Transformer.from_crs("EPSG:32610", "EPSG:26910", always_xy=True)
    counts = {m: Counter() for m in MARGINS}
    block_ids = {m: set() for m in MARGINS}
    transects = {m: set() for m in MARGINS}
    years = {m: set() for m in MARGINS}
    delta = {m: [] for m in MARGINS}
    seen = set()
    source_rows = 0
    reference_rows = 0
    with tempfile.TemporaryDirectory() as temp:
        extract_grids(archive, Path(temp))
        with rasterio.open(original_tiff(character)) as classes, \
             rasterio.open(Path(temp) / "ArcViewGrids" / GRIDS[0][0]) as shallow, \
             rasterio.open(Path(temp) / "ArcViewGrids" / GRIDS[1][0]) as deep, \
             rov_path.open(newline="", encoding="utf-8-sig") as stream:
            if (str(classes.crs) != "EPSG:32610" or classes.res != (2.0, 2.0)
                    or str(shallow.crs) != "EPSG:26910" or shallow.res != (2.0, 2.0)
                    or str(deep.crs) != "EPSG:26910" or deep.res != (5.0, 5.0)):
                raise ValueError("Original Point Buchon source CRS or grid size changed")
            import csv
            reader = csv.DictReader(stream)
            required = {"LongTerm_Region", "Protection", "Type", "Avg.X", "Avg.Y",
                        "Avg.Depth", "SurveyYear", "X10m_ID", "MPAGroup", "Propn_Hard",
                        "Lingcod"} | set(ROCKFISH)
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("Historical ROV source schema changed")
            for row in reader:
                source_rows += 1
                if (row["LongTerm_Region"] != "Central" or row["Protection"] != "0"
                        or row["Type"] != "Reference"):
                    continue
                reference_rows += 1
                depth = float(row["Avg.Depth"])
                if not LOWER_M <= depth <= UPPER_M:
                    continue
                ident = row["X10m_ID"]
                if ident in seen or "_" not in ident:
                    raise ValueError("Repeated or ungrouped ROV subunit")
                seen.add(ident)
                x, y = 1000 * float(row["Avg.X"]), 1000 * float(row["Avg.Y"])
                point = Point(x, y)
                matched = [int(i) for i in tree.query(point) if geometries[int(i)].contains(point)]
                if not matched:
                    continue
                if len(matched) != 1 or row["MPAGroup"] != "Point Buchon":
                    raise ValueError("ROV block or source-group relationship changed")
                block_id = matched[0]
                edge = point.distance(geometries[block_id].boundary)
                category = next(classes.sample([(x, y)], masked=True))[0]
                if getattr(category, "mask", False) or int(category) not in (1, 2, 3):
                    raise ValueError("ROV point no longer samples classified USGS bottom")
                category = int(category)
                grid_point = to_depth.transform(x, y)
                sampled_depth, spacing = source_depth_at(grid_point, shallow, deep)
                lingcod = float(row["Lingcod"]) > 0
                rockfish = any(float(row[key]) > 0 for key in ROCKFISH)
                visual_hard = float(row["Propn_Hard"]) >= 0.5
                partial_access_clear = not any(features[block_id]["properties"]["review_holds"].values())
                for margin in MARGINS:
                    if edge < margin:
                        continue
                    c = counts[margin]
                    c["subunits_in_blocks"] += 1
                    c["partial_access_clear_subunits"] += partial_access_clear
                    c["source_observed_majority_hard_subunits"] += visual_hard
                    c["source_lingcod_positive_subunits"] += lingcod
                    c["source_rockfish_positive_subunits"] += rockfish
                    if sampled_depth is None:
                        c["no_original_grid_cell_in_source_depth_band"] += 1
                    else:
                        c["original_grid_cell_in_source_depth_band"] += 1
                        c[f"grid_{spacing}m_subunits"] += 1
                        c[f"source_class_{category}_subunits"] += 1
                        c[f"source_class_{category}_visual_majority_hard_subunits"] += visual_hard
                        if category in (2, 3):
                            c["hard_class_subunits"] += 1
                            c["hard_class_lingcod_positive_subunits"] += lingcod
                            c["hard_class_rockfish_positive_subunits"] += rockfish
                        if category == 3:
                            c["rugose_class_subunits"] += 1
                        delta[margin].append(sampled_depth - depth)
                    block_ids[margin].add(block_id)
                    transects[margin].add(ident.rsplit("_", 1)[0])
                    years[margin].add(int(row["SurveyYear"]))
    if source_rows != 133506 or reference_rows < 10000:
        raise ValueError("Historical ROV source coverage changed")
    expected = {0: (138, 94), 10: (91, 62), 25: (37, 26)}
    if any((counts[m]["subunits_in_blocks"], counts[m]["original_grid_cell_in_source_depth_band"]) != expected[m]
           for m in MARGINS):
        raise ValueError("Historical ROV-to-original-cell relationship changed")
    summaries = {}
    for margin in MARGINS:
        c = counts[margin]
        summaries[str(margin)] = {
            **dict(sorted(c.items())),
            "distinct_research_blocks": len(block_ids[margin]),
            "partial_access_clear_blocks": sum(
                not any(features[i]["properties"]["review_holds"].values())
                for i in block_ids[margin]),
            "distinct_transect_labels": len(transects[margin]),
            "observation_years": sorted(years[margin]),
            "original_grid_minus_rov_observed_depth_m_range": [
                round(min(delta[margin]), 2), round(max(delta[margin]), 2)],
        }
    return {
        "schema_version": 1,
        "scope": "point-buchon-independent-original-cell-historical-rov-research-join",
        "historical_rov_doi": pin["doi"],
        "historical_rov_sha256": pin["file_sha256"],
        "original_csumb_archive_sha256": ARCHIVE_SHA256,
        "original_usgs_character_sha256": EXPECTED_CLASS,
        "publisher_character_accuracy": class_accuracy,
        "private_research_blocks_sha256": hashlib.sha256(block_path.read_bytes()).hexdigest(),
        "partial_access_screen_sha256": hashlib.sha256(json.dumps({
            key: value for key, value in access.items()
            if key not in ("source_checked_at", "input_sha256")
        }, sort_keys=True).encode()).hexdigest(),
        "source_rows_checked": source_rows,
        "central_open_reference_rows_checked": reference_rows,
        "source_depth_band_m": [LOWER_M, UPPER_M],
        "inward_block_sensitivity_m": summaries,
        "source_acquisition_year_at_grid_cells_verified": False,
        "rov_bottom_position_error_bounded": False,
        "cross_survey_horizontal_registration_bounded": False,
        "chart_mllw_depth_and_upper_uncertainty_verified": False,
        "full_route_and_fishing_date_cleared": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "ROV 10 m subunits and transects are correlated historical samples, not trips, catch rates or current fish predictions.",
            "A centroid on a source grid cell is not proof that the ROV camera imaged that exact cell; position and cross-survey registration errors are unbounded.",
            "The 2009-labeled CSUMB grid is packaged with 2007 bathymetry tracklines, so individual cell acquisition years remain unverified.",
            "The 2008 USGS character class is interpreted habitat. Class 2 hard-flat can include coarse sand and gravel, so its subunits are not evidence of boulders; class 3 hard-rugose is tracked separately. Publisher accuracy reused some training video observations and hard-flat majority agreement is 45.33 percent; neither that rate nor these ROV overlays validate a point without positional support and negative-sample analysis.",
            "The 0, 10 and 25 m inward block tests are sensitivity checks, not measured ROV position-error bounds.",
            "The MPA, federal and ENC results are partial block screens; source-datum depth is not a chart MLLW depth and no full route or current rule has been cleared.",
            "The receipt publishes aggregate counts only, without ROV coordinates, block IDs or fishing waypoints.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-rov", action="store_true")
    parser.add_argument("--rov", type=Path, default=ROV)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--character", type=Path, default=CHARACTER)
    parser.add_argument("--character-metadata", type=Path, default=CHARACTER_METADATA)
    parser.add_argument("--blocks", type=Path, default=BLOCKS)
    parser.add_argument("--access", type=Path, default=ACCESS)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-rov-original-cell-join.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch_rov:
        fetch(json.loads(PIN.read_text()), args.rov)
    report = build(args.rov, args.archive, args.character, args.blocks, args.access,
                   args.character_metadata)
    if args.verify and report != json.loads(args.verify.read_text()):
        raise SystemExit("Original-cell historical ROV evidence changed; review before ranking")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Joined historical open-reference ROV to original Point Buchon cells; zero fishing targets")


if __name__ == "__main__":
    main()

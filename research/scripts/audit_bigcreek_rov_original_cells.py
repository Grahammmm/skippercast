#!/usr/bin/env python3
"""Join historical Big Creek reference ROV subunits to Lopez original grids.

The aggregate is research evidence, not a public fishing target or a fish forecast.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import tarfile
import tempfile
import zipfile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import Window
from shapely.geometry import Point, shape
from shapely.ops import transform

from research.scripts.audit_bigcreek_original_grids import (
    ARCHIVE_SHA256, extract_grid, fetch_archive, fetch_mpas,
)
from research.scripts.build_central_rov_depth_evidence import fetch, source_bytes
from skippercast.platform.contracts import atomic_json


ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "catalog/central-rov-2024-source.json"
ROV = ROOT / "var/review/rov-zenodo-10929417.csv"
ARCHIVE = ROOT / "var/noaa-native-cache/BigCreek_additional_products.tar.gz"
OUTPUT = ROOT / "dist/data/bigcreek-lopez-rov-original-cell-join.json"
ROCKFISH = ("Copper_rf", "Gopher_rf", "Vermilion_rf", "Canary_rf",
            "Quillback_rf", "Yelloweye_rf", "Brown_rf")
SENSITIVITY_RADII_M = (10, 25)


def _product(original: tarfile.TarFile, kind: str) -> bytes:
    name = "BigCreek2010/LopezPt."
    matches = [item for item in original.getmembers()
               if item.name.startswith(name) and item.name.endswith(f"_{kind}.zip")]
    if len(matches) != 1 or matches[0].size > 50_000_000:
        raise ValueError(f"Original Lopez {kind} product changed")
    return original.extractfile(matches[0]).read()


def neighborhood_consistent(depth_grid, habitat_grid, point, radius_m: int,
                            category: int, spacing: int) -> bool:
    """Check all native cell centers within radius; not a positional-error bound."""
    x, y = point
    row, col = depth_grid.index(x, y)
    reach = math.ceil(radius_m / spacing) + 1
    window = Window(col - reach, row - reach, 2 * reach + 1, 2 * reach + 1)
    depth = depth_grid.read(1, window=window, masked=True, boundless=True)
    habitat = habitat_grid.read(1, window=window, masked=True, boundless=True)
    rows, cols = np.indices(depth.shape)
    affine = depth_grid.window_transform(window)
    centers_x = affine.c + (cols + 0.5) * affine.a
    centers_y = affine.f + (rows + 0.5) * affine.e
    circle = (centers_x - x) ** 2 + (centers_y - y) ** 2 <= radius_m ** 2
    if not circle.any():
        return False
    minimum, maximum = (60.96, 80.0) if spacing == 2 else (80.0, 91.44)
    band = (depth <= -minimum) & (depth >= -maximum) if spacing == 2 else \
        (depth < -minimum) & (depth >= -maximum)
    return bool((~np.ma.getmaskarray(depth)[circle]).all()
                and (~np.ma.getmaskarray(habitat)[circle]).all()
                and np.asarray(band)[circle].all()
                and np.asarray(habitat == category)[circle].all())


def build(rov_path: Path, archive_path: Path, mpas: dict, mpa_sha: str) -> dict:
    pin = json.loads(PIN.read_text())
    source_bytes(rov_path, pin)
    with archive_path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Original Big Creek archive changed")
    project = Transformer.from_crs("EPSG:4326", "EPSG:26910", always_xy=True).transform
    protected = [transform(project, shape(feature["geometry"])).buffer(75)
                 for feature in mpas["features"]]
    if {f["properties"]["NAME"] for f in mpas["features"]} != {"Big Creek SMCA", "Big Creek SMR"}:
        raise ValueError("Official protected areas changed")
    counts = Counter()
    years = set()
    transects = set()
    differences = []
    class_counts = defaultdict(Counter)
    with tempfile.TemporaryDirectory(prefix="skippercast-lopez-rov-") as temp:
        paths = {}
        with tarfile.open(archive_path, "r:gz") as original:
            for kind in ("bathygrids", "habitat"):
                product = _product(original, kind)
                with zipfile.ZipFile(io.BytesIO(product)) as zipped:
                    for spacing in (2, 5):
                        label = f"lp_{spacing}m" + ("bathy" if kind == "bathygrids" else "hab")
                        if "ArcViewGrids/" + label + "/metadata.xml" not in zipped.namelist():
                            raise ValueError("Original Lopez product member changed")
                        path, _ = extract_grid(product, "ArcViewGrids/" + label, Path(temp))
                        paths[label] = path
        with rasterio.open(paths["lp_2mbathy"]) as d2, rasterio.open(paths["lp_2mhab"]) as h2, \
             rasterio.open(paths["lp_5mbathy"]) as d5, rasterio.open(paths["lp_5mhab"]) as h5, \
             rov_path.open(newline="", encoding="utf-8-sig") as stream:
            for spacing, depth, habitat in ((2, d2, h2), (5, d5, h5)):
                if (depth.crs.to_epsg() != 26910 or depth.res != (float(spacing), float(spacing))
                        or depth.shape != habitat.shape or depth.transform != habitat.transform):
                    raise ValueError("Original Lopez grid registration changed")
            reader = csv.DictReader(stream)
            required = {"LongTerm_Region", "MPAGroup", "Protection", "Type", "X10m_ID",
                        "Avg.X", "Avg.Y", "Avg.Depth", "SurveyYear", "Usable_Area_Fish",
                        "Propn_Hard", "Propn_Mixed", "Lingcod"} | set(ROCKFISH)
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("Historical ROV schema changed")
            seen = set()
            for row in reader:
                counts["source_rows"] += 1
                if (row["LongTerm_Region"] != "Central" or row["MPAGroup"] != "Big Creek"
                        or row["Protection"] != "0" or row["Type"] != "Reference"):
                    continue
                depth_observed = float(row["Avg.Depth"])
                if not 60.96 <= depth_observed <= 91.44:
                    continue
                ident = row["X10m_ID"]
                if ident in seen or "_" not in ident:
                    raise ValueError("Repeated or ungrouped ROV subunit")
                seen.add(ident)
                counts["deep_big_creek_reference_subunits"] += 1
                x, y = 1000 * float(row["Avg.X"]), 1000 * float(row["Avg.Y"])
                point = (x, y)
                # The published 2 m and 5 m products overlap. Select one tier
                # from the original-grid depth, with 80 m assigned to 2 m.
                selected = None
                for spacing, depth_grid, habitat_grid, lo, hi in (
                        (2, d2, h2, 60.96, 80.0), (5, d5, h5, 80.0, 91.44)):
                    value = next(depth_grid.sample([point], masked=True))[0]
                    category = next(habitat_grid.sample([point], masked=True))[0]
                    if np.ma.is_masked(value) or np.ma.is_masked(category):
                        continue
                    grid_depth = -float(value)
                    in_band = lo <= grid_depth <= hi if spacing == 2 else lo < grid_depth <= hi
                    if in_band:
                        selected = (spacing, grid_depth, int(category))
                        break
                if selected is None:
                    counts["no_paired_original_cell_in_source_depth_band"] += 1
                    continue
                counts["paired_original_cell_in_source_depth_band"] += 1
                if any(polygon.covers(Point(x, y)) for polygon in protected):
                    counts["inside_mpa_plus_75m_screen"] += 1
                    continue
                spacing, grid_depth, category = selected
                if category not in (-31, -30):
                    raise ValueError("Original Lopez habitat class changed")
                if float(row["Usable_Area_Fish"]) <= 0:
                    raise ValueError("ROV observation has no usable area")
                hard, mixed = float(row["Propn_Hard"]), float(row["Propn_Mixed"])
                if not (0 <= hard <= 1 and 0 <= mixed <= 1 and hard + mixed <= 1.002):
                    raise ValueError("ROV habitat fractions changed")
                lingcod = float(row["Lingcod"]) > 0
                rockfish = any(float(row[key]) > 0 for key in ROCKFISH)
                visual_hard = hard >= 0.5
                key = "derived_rough" if category == -31 else "derived_smooth"
                c = class_counts[key]
                c["subunits"] += 1
                c[f"grid_{spacing}m_subunits"] += 1
                c["visual_majority_hard_subunits"] += visual_hard
                c["lingcod_positive_subunits"] += lingcod
                c["rockfish_positive_subunits"] += rockfish
                depth_grid, habitat_grid = (d2, h2) if spacing == 2 else (d5, h5)
                for radius in SENSITIVITY_RADII_M:
                    if neighborhood_consistent(depth_grid, habitat_grid, point, radius,
                                               category, spacing):
                        c[f"same_class_and_band_within_{radius}m_cell_centers"] += 1
                differences.append(grid_depth - depth_observed)
                years.add(int(row["SurveyYear"]))
                transects.add(ident.rsplit("_", 1)[0])
                counts["outside_mpa_plus_75m_screen"] += 1
    if counts["source_rows"] != 133506 or counts["deep_big_creek_reference_subunits"] != 396:
        raise ValueError("Historical ROV coverage changed")
    return {
        "schema_version": 1,
        "scope": "bigcreek-lopez-historical-rov-original-cell-research-join",
        "historical_rov_doi": pin["doi"],
        "historical_rov_sha256": pin["file_sha256"],
        "original_csumb_archive_sha256": ARCHIVE_SHA256,
        "cdfw_mpa_raw_sha256": mpa_sha,
        "source_depth_band_m": [60.96, 91.44],
        "source_vertical_datum": "NAVD88 Geoid09",
        "tier_rule": "2 m for 60.96–80 m source depth; 5 m for >80–91.44 m; each subunit counted once",
        "neighborhood_sensitivity_radii_m": list(SENSITIVITY_RADII_M),
        "mpa_review_buffer_m": 75,
        "counts": dict(sorted(counts.items())),
        "historical_observation_years_outside_screen": sorted(years),
        "distinct_transect_labels_outside_screen": len(transects),
        "outside_screen_by_derived_class": {
            key: {**dict(sorted(class_counts[key].items())),
                  **{f"same_class_and_band_within_{radius}m_cell_centers":
                     class_counts[key][f"same_class_and_band_within_{radius}m_cell_centers"]
                     for radius in SENSITIVITY_RADII_M}}
            for key in ("derived_rough", "derived_smooth")},
        "grid_minus_rov_observed_depth_m_range": [round(min(differences), 2), round(max(differences), 2)] if differences else None,
        "rov_bottom_position_error_bounded": False,
        "cross_survey_registration_bounded": False,
        "chart_mllw_depth_and_upper_uncertainty_verified": False,
        "source_acquisition_year_at_grid_cells_verified": False,
        "full_route_and_fishing_date_cleared": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "Historical ROV 10 m subunits are correlated within transects and do not measure catch rates or current fish presence.",
            "A subunit average position sampled against a raster cell does not prove the camera imaged that cell; position and cross-survey error bounds are unavailable.",
            "The 10 m and 25 m circular native-cell-center checks are sensitivity tests, not measured camera position error or complete-footprint clearance.",
            "The 75 m MPA proximity screen is research-only, not a legal fishing boundary or current trip clearance.",
            "The source depth is NAVD88 rather than MLLW, and the bathymetry/habitat cells are processed and interpolated, not independent soundings or rock observations.",
            "Only aggregate evidence is published; no historical observation positions or fishing coordinates are released.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rov", type=Path, default=ROV)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--fetch-rov", action="store_true")
    parser.add_argument("--fetch-archive", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch_rov:
        fetch(json.loads(PIN.read_text()), args.rov)
    if args.fetch_archive:
        fetch_archive(args.archive)
    mpas, mpa_sha = fetch_mpas()
    result = build(args.rov, args.archive, mpas, mpa_sha)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("Lopez original-cell historical ROV relationship changed; review before use")
    atomic_json(args.output, result)
    print(json.dumps({"counts": result["counts"], "fishing_target": False}))


if __name__ == "__main__":
    main()

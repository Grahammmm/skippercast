#!/usr/bin/env python3
"""Check original 2010 SCC grids against private 2012 Estero research blocks.

Original 2 m CSUMB grids are independent survey coverage, not charted depth or
independent fish/rock groundtruth. Only aggregate source coverage is published.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
from urllib.request import Request, urlopen
import zipfile

import numpy as np
from pyproj import Transformer
import rasterio
from shapely import contains_xy
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

from scripts.audit_usgs_estero_2012_original import ARCHIVES, ascii_member, header

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    12: {"archive_sha256": "e2e3b2d0db017ab3160a5c2184b2b87e2aba25eb35b7807809188cea51bd211b",
         "archive_bytes": 330668756,
         "member": "SCC_Blk12_2m_bathygrid.zip",
         "member_sha256": "bbbb9c45accf1090d83c56e9fec8f6bc490b622cf2ae68b2d973f127653478c7",
         "metadata_sha256": "0de0cb3e6c86825f03a86d3fec2fbff175924ddb1373d4eeadd442a438b9e473"},
    13: {"archive_sha256": "ee72aa92a3ffad81a0630fa35519383aa7a33159a44094ad3ca7fd3052a06cdd",
         "archive_bytes": 150142162,
         "member": "SCC_Blk13_2m_bathygrids.zip",
         "member_sha256": "268e3188fed8bb83647f0974d4a6da18a979e34592aea478d6333047bf5fdd2e",
         "metadata_sha256": "010acc3fb2a4f6d86438510e6b532a3c9081c3d486b9126768de98b1e44f3e6c"},
}
BANDS = ("200-250ft", "250-300ft")


def fetch_original(path, sid):
    pin = SOURCES[sid]
    if path.exists():
        if path.stat().st_size != pin["archive_bytes"] or sha256(path.read_bytes()) != pin["archive_sha256"]:
            raise ValueError("Existing original CSUMB archive changed")
        return
    url = (f"https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/SCC_Block{sid}/"
           f"multibeam/data/version2/products/SCC_Block{sid}_additional_products.tar.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with urlopen(Request(url, headers={"User-Agent": "SkipperCast original survey audit"}), timeout=90) as response, temporary.open("wb") as output:
            if response.status != 200 or response.url != url:
                raise ValueError("NOAA original survey archive failed or redirected")
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > pin["archive_bytes"]:
                    raise ValueError("NOAA original survey archive exceeds pinned size")
                digest.update(chunk)
                output.write(chunk)
        if size != pin["archive_bytes"] or digest.hexdigest() != pin["archive_sha256"]:
            raise ValueError("NOAA original survey archive bytes changed")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def original_grid(archive_path, sid, destination):
    pin = SOURCES[sid]
    if sha256(archive_path.read_bytes()) != pin["archive_sha256"]:
        raise ValueError(f"CSUMB SCC Block{sid} original archive changed")
    with tarfile.open(archive_path) as tar:
        members = [m for m in tar.getmembers() if m.isfile() and m.name == pin["member"]]
        if len(members) != 1:
            raise ValueError("Original bathymetry member missing or duplicated")
        payload = tar.extractfile(members[0]).read()
    if sha256(payload) != pin["member_sha256"]:
        raise ValueError("Original bathymetry member changed")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        grid = f"ArcViewGrids/scc{sid}_2mbathy"
        metadata = grid + "/metadata.xml"
        if metadata not in names or sha256(archive.read(metadata)) != pin["metadata_sha256"]:
            raise ValueError("Original bathymetry metadata changed")
        text = archive.read(metadata).decode("utf-8", errors="replace")
        if "NAVD88 Geoid09" not in text or "± 20 cm vertical, but varies with depth" not in text:
            raise ValueError("Original vertical reference or accuracy caveat changed")
        for item in archive.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Unsafe original archive path")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
    return destination / grid


def inspect_grid(grid_path, blocks):
    reproject = Transformer.from_crs("EPSG:32610", "EPSG:26910", always_xy=True).transform
    by_band = {label: {"research_blocks": 0, "blocks_with_measured_2010_cells": 0,
                       "measured_2010_cells": 0,
                       "2010_cells_in_same_nominal_navd88_band": 0}
               for label in BANDS}
    with rasterio.open(grid_path) as grid:
        if str(grid.crs) != "EPSG:26910" or grid.count != 1 or grid.res != (2.0, 2.0):
            raise ValueError("Original 2010 bathymetry grid geometry changed")
        for feature in blocks["features"]:
            label = feature["properties"]["band"]
            if label not in by_band or feature["properties"].get("fishing_target") is not False:
                raise ValueError("Unreviewed research block")
            result = by_band[label]
            result["research_blocks"] += 1
            polygon = transform(reproject, shape(feature["geometry"]))
            overlap = polygon.intersection(box(*grid.bounds))
            if overlap.is_empty:
                continue
            window = from_bounds(*overlap.bounds, transform=grid.transform).round_offsets().round_lengths()
            window = window.intersection(Window(0, 0, grid.width, grid.height))
            data = grid.read(1, window=window, masked=True)
            inside = geometry_mask([mapping(overlap)], out_shape=data.shape,
                                   transform=grid.window_transform(window), invert=True)
            values = data[np.logical_and(inside, ~data.mask)]
            result["measured_2010_cells"] += len(values)
            if values.size:
                result["blocks_with_measured_2010_cells"] += 1
                low, high = (int(x) for x in label.removesuffix("ft").split("-"))
                depth_ft = -values * 3.280839895
                result["2010_cells_in_same_nominal_navd88_band"] += int(
                    np.count_nonzero((depth_ft >= low) & (depth_ft < high)))
        return by_band, {"crs": str(grid.crs), "resolution_m": list(grid.res),
                         "native_depth_min_m": float(grid.read(1, masked=True).min())}


def compare_depth(grid_path, blocks, depth_2012):
    if sha256(depth_2012.read_bytes()) != ARCHIVES[depth_2012.name]:
        raise ValueError("Original 2012 Estero depth archive changed")
    shallow = unary_union([shape(feature["geometry"]) for feature in blocks["features"]
                           if feature["properties"]["band"] == "200-250ft"])
    to_class_frame = Transformer.from_crs("EPSG:26910", "EPSG:32610", always_xy=True)
    archive, source = ascii_member(depth_2012)
    differences = []
    try:
        layout = header(source)
        if (layout["xllcorner"] != 665811.16966312
                or layout["yllcorner"] != 3900237.4867247
                or layout["cellsize"] != 2):
            raise ValueError("2012 Estero depth grid registration changed")
        ncol, nrow = int(layout["ncols"]), int(layout["nrows"])
        xs = layout["xllcorner"] + (np.arange(ncol) + .5) * 2
        with rasterio.open(grid_path) as grid:
            native = grid.read(1, masked=True)
            for row in range(nrow):
                line = np.fromstring(source.readline().decode("ascii"), sep=" ")
                if line.size != ncol:
                    raise ValueError(f"Truncated 2012 Estero depth row {row}")
                y = layout["yllcorner"] + (nrow - row - .5) * 2
                if y < grid.bounds.bottom or y > grid.bounds.top:
                    continue
                x2, y2 = to_class_frame.transform(xs, np.full(ncol, y))
                selected = np.where((line != -9999)
                                    & (-line >= 200 / 3.280839895)
                                    & (-line < 250 / 3.280839895)
                                    & contains_xy(shallow, x2, y2))[0]
                if not selected.size:
                    continue
                cols = np.floor((xs[selected] - grid.bounds.left) / 2).astype("int32")
                rows = np.full(len(selected), int(np.floor((grid.bounds.top - y) / 2)))
                inside = ((cols >= 0) & (cols < grid.width)
                          & (rows >= 0) & (rows < grid.height))
                if not inside.any():
                    continue
                values = native[rows[inside], cols[inside]]
                populated = ~np.ma.getmaskarray(values)
                differences.extend((values[populated] - line[selected[inside]][populated]).tolist())
    finally:
        source.close()
        archive.close()
    if not differences:
        return {"matched_native_cells": 0, "median_2010_minus_2012_m": None,
                "p95_abs_difference_m": None}
    values = np.asarray(differences)
    return {"matched_native_cells": len(values),
            "median_2010_minus_2012_m": round(float(np.median(values)), 3),
            "p95_abs_difference_m": round(float(np.quantile(np.abs(values), .95)), 3)}


def audit(archives, private_blocks, depth_2012):
    blocks = json.loads(private_blocks.read_text())
    if (blocks.get("scope") != "private-estero-nominal-research-blocks"
            or blocks.get("crs") != "EPSG:32610"
            or len(blocks.get("features", [])) != 60):
        raise ValueError("Private Estero research block inventory changed")
    source_results = []
    for sid in SOURCES:
        with tempfile.TemporaryDirectory(prefix=f"scc-{sid}-") as temporary:
            grid_path = original_grid(archives[sid], sid, Path(temporary))
            bands, native = inspect_grid(grid_path, blocks)
            comparison = compare_depth(grid_path, blocks, depth_2012)
        source_results.append({"survey_id": f"SCC_Block{sid}", "survey_year": 2010,
                               "source_url": f"https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block{sid}_mb.html",
                               "archive_sha256": SOURCES[sid]["archive_sha256"],
                               "native_vertical_datum": "NAVD88 Geoid09",
                               "native": native, "bands": bands,
                               "nominal_2010_2012_depth_comparison": comparison})
    if any(row["bands"]["250-300ft"]["measured_2010_cells"] != 0 for row in source_results):
        raise ValueError("Previously absent original deeper 2010 coverage now exists; review before release")
    return {"schema_version": 1, "scope": "csumb-scc-2010-estero-original-research-block-coverage",
            "private_block_count": len(blocks["features"]), "source_results": source_results,
            "source_2012_archive_sha256": ARCHIVES[depth_2012.name],
            "fishing_target": False, "exportable": False, "qualified_waypoints": 0,
            "limitations": ["2010 SCC grids are original measured coverage, but their NAVD88 Geoid09 elevations are not MLLW chart depths.",
                            "The source metadata states ±20 cm vertical accuracy varies with depth; it supplies no per-cell upper bound.",
                            "The 2010 habitat grid derives ruggedness from the 2010 depth grid and is not independent rock or fish groundtruth.",
                            "Nominal 2010-minus-2012 nearest-cell differences in the overlapping shallow blocks combine geoid09/geoid12, epoch/registration, resampling, survey and possible seabed-change effects; their 95th percentile is not an upper depth-uncertainty bound.",
                            "Research blocks aggregate 2012 depth and 2008 class cells; 2010 cells within a block do not prove exact cell registration, unchanged bottom, or a fishing coordinate."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block12", type=Path, default=ROOT / "var/review/csumb-scc-estero/SCC_Block12_additional_products.tar.gz")
    parser.add_argument("--block13", type=Path, default=ROOT / "var/review/csumb-scc-estero/SCC_Block13_additional_products.tar.gz")
    parser.add_argument("--private-blocks", type=Path, default=ROOT / "var/review/estero-nominal-research-blocks.geojson")
    parser.add_argument("--depth-2012", type=Path, default=ROOT / "var/review/estero-bay-2012/NAD83_utm10_EsteroBay.zip")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/csumb-scc-2010-estero-original-block-coverage.json")
    args = parser.parse_args()
    if args.fetch:
        fetch_original(args.block12, 12)
        fetch_original(args.block13, 13)
    result = audit({12: args.block12, 13: args.block13}, args.private_blocks, args.depth_2012)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print([(row["survey_id"], row["bands"]["200-250ft"]["blocks_with_measured_2010_cells"],
            row["bands"]["250-300ft"]["blocks_with_measured_2010_cells"])
           for row in result["source_results"]])


if __name__ == "__main__":
    main()

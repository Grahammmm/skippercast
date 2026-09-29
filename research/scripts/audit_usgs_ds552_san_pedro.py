"""Audit original USGS DS 552 San Pedro rock classes against 2004 video.

Produces an unpublished review queue. Historical substrate is neither a fish
observation nor a depth-, access-, chart-, or regulations-qualified target.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile
import tempfile
import zipfile

import numpy as np
from pyproj import Transformer
import rasterio
from scipy.ndimage import find_objects, label
import shapefile


SOURCES = {
    "inner": ("inner_shelf_character_tif.zip", "2b33541c5783476868894e66fdd7d834c69410d6962ac07afcaeefeef367382d",
              "https://pubs.usgs.gov/ds/552/data/raster/inner_shelf_character_tif.zip"),
    "outer": ("outer_shelf_character_tif.zip", "4dbb90f778459da4324c19df6df570d3c7013acf41d9c67613b49fd6483bd186",
              "https://pubs.usgs.gov/ds/552/data/raster/outer_shelf_character_tif.zip"),
    "video": ("videodes_shp.zip", "76797f9b029d50fffc363c4dd800aaae0940699a1a27a27432c3c02773db1af8",
              "https://pubs.usgs.gov/ds/552/data/shp_files/videodes_shp.zip"),
}
DEPTH_SOURCES = {
    "pvebat": ("e4bf14283305843c4a965f7e1ecec3b22228b5e06560dc068ab26dd7fd1ad314",
               "https://pubs.usgs.gov/of/2004/1221/data/grid/pvebat.tgz"),
    "gabbat": ("6db3fd2a3ebe33e3ccda1581a3e563c20a5207a4dea29c783ebffff15a91cc11",
               "https://pubs.usgs.gov/of/2004/1221/data/grid/gabbat.tgz"),
    "spbbat": ("96c0e4743789f9bbdd9fdb0b68df2cdf5d25cdb20bb214f201152ef3625afd0b",
               "https://pubs.usgs.gov/of/2004/1221/data/grid/spbbat.tgz"),
}
CLASSES = {0: "undefined", 1: "rugose rock", 2: "sand", 3: "mixed rock and sand",
           4: "muddy sand", 5: "coarse sand and shell"}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive_member(archive: Path, suffix: str) -> bytes:
    with zipfile.ZipFile(archive) as bundle:
        names = [name for name in bundle.namelist() if name.lower().endswith(suffix)]
        if len(names) != 1 or ".." in Path(names[0]).parts:
            raise ValueError(f"Unexpected {suffix} member in {archive.name}")
        return bundle.read(names[0])


def validate_raster(ds, resolution: int) -> np.ndarray:
    if (ds.crs is None or ds.crs.to_epsg() != 32611 or ds.count != 1
            or ds.res != (resolution, resolution) or ds.dtypes[0] != "uint8"):
        raise ValueError("USGS DS 552 raster grid identity changed")
    array = ds.read(1)
    if set(np.unique(array).tolist()) != set(CLASSES):
        raise ValueError("USGS DS 552 character classes changed")
    return array


def audit_depth_support(queue: list[dict], depth_cache: Path,
                        native_cells: tuple[np.ndarray, list[tuple[float, float]]]) -> dict:
    """Compare original MLLW grids at references and every mapped rock cell."""
    points = [tuple(row["bbox_center_lon_lat"]) for row in queue]
    cell_ids, cell_points = native_cells
    cell_depth = np.full(len(cell_points), np.nan)
    cell_overlap = np.zeros(len(cell_points), dtype="uint8")
    cell_max_disagreement = np.zeros(len(cell_points))
    matched = defaultdict(list)
    for name, (expected, _) in DEPTH_SOURCES.items():
        archive = depth_cache / f"{name}.tgz"
        if sha256(archive) != expected:
            raise ValueError(f"USGS OF 2004-1221 {name} archive changed")
        with tempfile.TemporaryDirectory(prefix=f"usgs-{name}-", dir=depth_cache) as directory:
            root = Path(directory)
            with zipfile.ZipFile(archive) as outer:
                if outer.namelist() != [f"{name}.tar"]:
                    raise ValueError("USGS bathymetry package changed")
                inner_bytes = outer.read(f"{name}.tar")
            with tarfile.open(fileobj=BytesIO(inner_bytes), mode="r:") as inner:
                if any(not (part.name == name or part.name.startswith(name + "/"))
                       or part.issym() or part.islnk() for part in inner.getmembers()):
                    raise ValueError("USGS bathymetry archive paths changed")
                inner.extractall(root, filter="data")
            with rasterio.open(root / name / f"{name}g") as ds:
                if (ds.driver != "AIG" or ds.crs is None or ds.crs.to_epsg() != 32611
                        or ds.res != (4.0, 4.0) or ds.count != 1):
                    raise ValueError("USGS original MLLW bathymetry grid changed")
                to_grid = Transformer.from_crs(4326, ds.crs, always_xy=True)
                samples = ds.sample([to_grid.transform(*point) for point in points])
                for row, sample in zip(queue, samples):
                    value = float(sample[0])
                    if np.isfinite(value) and value != ds.nodata and -200 * .3048 <= value <= -25 * .3048:
                        matched[row["component_id"]].append({"grid": name,
                            "center_depth_ft_below_mllw": round(-value / .3048, 1)})
                values = np.fromiter((float(sample[0]) for sample in ds.sample(cell_points)),
                                     dtype="float64", count=len(cell_points))
                valid = np.isfinite(values) & (values != ds.nodata) & (values < 0)
                overlapping = valid & np.isfinite(cell_depth)
                cell_max_disagreement[overlapping] = np.maximum(
                    cell_max_disagreement[overlapping],
                    np.abs(cell_depth[overlapping] - values[overlapping]))
                cell_overlap[valid] += 1
                new = valid & ~np.isfinite(cell_depth)
                cell_depth[new] = values[new]
    footprint = []
    for row in queue:
        row["original_center_depth_samples"] = matched[row["component_id"]]
        selection = cell_ids == row["component_id"]
        total = int(selection.sum())
        if total * 16 != row["rock_class_area_m2"]:
            raise ValueError("Rock component cell count changed during depth join")
        values = cell_depth[selection]
        observed = values[np.isfinite(values)]
        feet = -observed / .3048
        band = (feet >= 25) & (feet <= 200)
        result = {"component_id": row["component_id"], "rock_cells": total,
                  "depth_covered_cells": len(observed),
                  "depth_cells_in_25_to_200_ft_mllw": int(band.sum()),
                  "sampled_rock_depth_ft_range": [round(float(feet.min()), 1),
                                                  round(float(feet.max()), 1)] if len(feet) else None,
                  "overlapping_source_cells": int(np.count_nonzero(cell_overlap[selection] > 1)),
                  "maximum_overlapping_grid_disagreement_m": round(
                      float(cell_max_disagreement[selection].max()), 3),
                  "whole_footprint_depth_band_supported": bool(len(observed) == total and band.all()),
                  "fishing_target": False, "exportable": False}
        row["original_full_rock_depth_review"] = result
        footprint.append(result)
    return {"original_grid_count": len(DEPTH_SOURCES),
            "review_queue_centers_in_25_to_200_ft_mllw": sum(bool(matched[row["component_id"]]) for row in queue),
            "rock_cells_reviewed": len(cell_points),
            "fully_depth_covered_rock_components": sum(item["depth_covered_cells"] == item["rock_cells"]
                                                        for item in footprint),
            "whole_footprint_depth_band_supported_components": sum(item["whole_footprint_depth_band_supported"]
                                                                    for item in footprint),
            "maximum_overlapping_grid_disagreement_m": max(
                item["maximum_overlapping_grid_disagreement_m"] for item in footprint),
            "depth_source_archives": {name: {"url": value[1], "sha256": value[0]}
                                      for name, value in DEPTH_SOURCES.items()},
            "depth_basis_url": "https://pubs.usgs.gov/of/2004/1221/metadata/labathygrd.html",
            "depth_limitation": "Every historical 4 m rugose-rock class cell sampled against original MLLW grids, but grids do not supply per-cell uncertainty. Publisher warns of collection and processing artifacts. This is a depth-band research screen, not a current fishing or navigation clearance."}


def review(cache: Path, depth_cache: Path | None = None) -> dict:
    archives = {key: cache / row[0] for key, row in SOURCES.items()}
    for key, path in archives.items():
        if sha256(path) != SOURCES[key][1]:
            raise ValueError(f"USGS DS 552 {key} archive changed; manual source review required")
    # pyshp can read original shapefile and DBF directly from their verified ZIP.
    video_zip = archives["video"]
    reader = shapefile.Reader(shp=BytesIO(archive_member(video_zip, ".shp")),
                              shx=BytesIO(archive_member(video_zip, ".shx")),
                              dbf=BytesIO(archive_member(video_zip, ".dbf")))
    if reader.shapeTypeName != "POINT" or len(reader) != 5216:
        raise ValueError("USGS camera observation table changed")
    observations = []
    for item in reader.iterShapeRecords():
        fields = item.record.as_dict()
        lon, lat = item.shape.points[0]
        observations.append((lon, lat, any(fields[key] == 1 for key in ("rock", "boulder", "cobble"))))
    rasters = {}
    native_cells = None
    for key, resolution in (("inner", 4), ("outer", 16)):
        data = archive_member(archives[key], ".tif")
        with rasterio.io.MemoryFile(data) as memory, memory.open() as ds:
            pixels = validate_raster(ds, resolution)
            counts = np.bincount(pixels.ravel(), minlength=6)
            transformer = Transformer.from_crs(4326, ds.crs, always_xy=True)
            sampled, hard = Counter(), Counter()
            positions = []
            for lon, lat, observed_hard in observations:
                row, col = ds.index(*transformer.transform(lon, lat))
                if 0 <= row < ds.height and 0 <= col < ds.width:
                    value = int(pixels[row, col])
                    sampled[value] += 1
                    if observed_hard:
                        hard[value] += 1
                    positions.append((row, col, observed_hard))
            rasters[key] = {
                "resolution_m": resolution, "crs": "EPSG:32611",
                "counts": {CLASSES[i]: int(counts[i]) for i in CLASSES},
                "video_samples_by_class": {CLASSES[i]: sampled[i] for i in CLASSES},
                "hard_video_samples_by_class": {CLASSES[i]: hard[i] for i in CLASSES},
                "bounds_utm11_m": [round(v, 3) for v in ds.bounds],
            }
            if key == "inner":
                component, total = label(pixels == 1)
                size = np.bincount(component.ravel(), minlength=total + 1)
                video_by_component = defaultdict(lambda: {"hard": 0, "all": 0})
                for row, col, observed_hard in positions:
                    ident = int(component[row, col])
                    if ident:
                        video_by_component[ident]["all"] += 1
                        video_by_component[ident]["hard"] += int(observed_hard)
                windows = find_objects(component)
                queue = []
                for ident, counts_at in video_by_component.items():
                    area = int(size[ident] * 16)
                    if area < 2500 or counts_at["hard"] == 0:
                        continue
                    window = windows[ident - 1]
                    center_row = (window[0].start + window[0].stop - 1) / 2
                    center_col = (window[1].start + window[1].stop - 1) / 2
                    x, y = ds.xy(center_row, center_col)
                    lon, lat = Transformer.from_crs(ds.crs, 4326, always_xy=True).transform(x, y)
                    queue.append({"component_id": ident, "rock_class_area_m2": area,
                                  "video_hard_observations": counts_at["hard"],
                                  "video_samples_on_component": counts_at["all"],
                                  "bbox_center_lon_lat": [round(lon, 6), round(lat, 6)],
                                  "fishing_target": False, "exportable": False})
                queue.sort(key=lambda row: (-row["rock_class_area_m2"], row["component_id"]))
                chosen = np.array([row["component_id"] for row in queue])
                yy, xx = np.where(np.isin(component, chosen))
                east, north = rasterio.transform.xy(ds.transform, yy, xx)
                native_cells = (component[yy, xx], list(zip(east, north)))
                rasters[key]["rock_components_at_least_2500_m2"] = int(np.count_nonzero(size[1:] >= 157))
                rasters[key]["video_supported_rock_components_at_least_2500_m2"] = len(queue)
    depth = audit_depth_support(queue, depth_cache, native_cells) if depth_cache else None
    return {
        "schema_version": 1, "scope": "usgs-ds552-san-pedro-original-rock-camera-review",
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publication_url": "https://pubs.usgs.gov/ds/552/",
        "source_archives": {key: {"url": row[2], "sha256": row[1]} for key, row in SOURCES.items()},
        "survey_period": "1998–2004; video observations from September 2004",
        "historical_video_rows": len(observations),
        "rasters": rasters,
        "inner_rock_review_queue": queue,
        "original_depth_review": depth,
        "fishing_target": False, "exportable": False,
        "required_next_gates": ["Defensible original-bathymetry uncertainty and artifact review for every candidate component",
                                "Fresh CDFW MPA and federal area polygon exclusions",
                                "Current NOAA charted hazards and safe route review",
                                "Date/method/species-specific CDFW rules and local access",
                                "Current conditions and independent habitat or catch validation"],
        "limitations": ["Component centers are bounding-box references, not fishing waypoints or chart positions.",
                        "Camera samples on a tow transect are correlated and do not imply independent confirmation or current fish presence.",
                        "The categorical character raster has no measured depth or boulder-size field; rock-class area is historical mapped habitat, not a quality score.",
                        "No research queue location may appear in the public target map or export before all required gates pass."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("var/review/usgs-ds552"))
    parser.add_argument("--depth-cache", type=Path)
    parser.add_argument("--output", type=Path, default=Path("var/review/usgs-ds552-san-pedro-review.json"))
    args = parser.parse_args()
    result = review(args.cache, args.depth_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2) + "\n")
    temp.replace(args.output)
    print(json.dumps({"video_supported_rock_components": len(result["inner_rock_review_queue"]),
                      "center_depth_hits": (result["original_depth_review"] or {}).get(
                          "review_queue_centers_in_25_to_200_ft_mllw"),
                      "fishing_targets": 0}))


if __name__ == "__main__":
    main()

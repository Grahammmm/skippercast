#!/usr/bin/env python3
"""Join original W00614 200–300 ft cells to original USGS Pigeon Point classes.

The output is a source-coverage receipt. It does not clear protected areas,
charted dangers, a route, current rules or fish presence.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

import h5py
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

from scripts.screen_vr_native_depth import fine_grid_rows
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, vr_transform


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire(url, expected_sha, path, max_bytes, fetch):
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        with urlopen(Request(url, headers={"User-Agent": "SkipperCast original-source audit/1.0"}),
                     timeout=90) as response, temporary.open("wb") as output:
            if response.status != 200 or response.url != url:
                raise ValueError("Original source redirected or failed")
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise ValueError("Original source exceeds bounded size")
                output.write(block)
        if sha256(temporary) != expected_sha:
            temporary.unlink(missing_ok=True)
            raise ValueError("Downloaded original source changed")
        temporary.replace(path)
    if path.stat().st_size > max_bytes or sha256(path) != expected_sha:
        raise ValueError("Cached original source changed")


def classified_counts(placed, eligible):
    """USGS nodata is -128; modulo tests must never classify negative nodata."""
    valid = placed > 0
    selected = eligible & valid
    return {"classified": int(selected.sum()),
            "hard_flat": int((selected & (placed % 10 == 2)).sum()),
            "hard_rugose": int((selected & (placed % 10 == 3)).sum()),
            "soft_flat": int((selected & (placed % 10 == 1)).sum())}


def audit(binding, bag_path, character_path):
    if (binding.get("scope") != "original-pigeon-point-noaa-depth-usgs-character-overlap"
            or binding.get("survey_id") != "W00614"
            or binding.get("release_gate") != "research-only"):
        raise ValueError("Unreviewed original-source binding")
    if sha256(bag_path) != binding["bag_sha256"] or sha256(character_path) != binding["character_sha256"]:
        raise ValueError("Original source changed")
    uri = f"/vsizip/{character_path.resolve()}/{binding['character_tif']}"
    source = json.loads(Path("dist/data/w00614-original-300-pigeon-monterey-review.json").read_text())
    if (source.get("source_sha256") != binding["bag_sha256"]
            or source.get("source_url") != binding["bag_url"]
            or source.get("counts", {}).get("depth_uncertainty_qualified_200_300ft_cells") != 141331):
        raise ValueError("W00614 depth source receipt changed")
    counts = {key: 0 for key in ("fine_supergrids_with_qualified_depth",
                                 "qualified_depth_cells", "classified", "hard_flat",
                                 "hard_rugose", "soft_flat")}
    with h5py.File(bag_path) as bag, rasterio.open(bag_path) as overview, rasterio.open(uri) as character:
        root = bag["BAG_root"]
        metadata = bag_metadata(root["metadata"][:].tobytes().decode().rstrip("\0"), "W00614")
        if (metadata["vertical_datum"] != "MLLW" or metadata["uncertainty_type"] != "productUncert"
                or character.crs.to_epsg() != 26910 or character.nodata != -128
                or character.res != (2.0, 2.0)
                or root["tracking_list"].size or root["varres_tracking_list"].size):
            raise ValueError("Original BAG or character metadata changed")
        refinements = root["varres_refinements"]
        grids = root["varres_metadata"][:]
        for row, col in fine_grid_rows(grids):
            item = grids[row, col]
            nx, ny = int(item["dimensions_x"]), int(item["dimensions_y"])
            transform = vr_transform(overview.bounds.left, overview.bounds.bottom,
                                     *overview.res, int(row), int(col), item)
            west, south, east, north = transform.c, transform.f - ny * abs(transform.e), transform.c + nx * transform.a, transform.f
            if (east < character.bounds.left or west > character.bounds.right
                    or north < character.bounds.bottom or south > character.bounds.top):
                continue
            offset = int(item["index"])
            if offset < 0 or offset + nx * ny > refinements.shape[1]:
                raise ValueError("Refinement index outside original BAG")
            values = refinements[0, offset:offset + nx * ny].reshape(ny, nx)[::-1]
            eligible = cells_qualified(values["depth"], values["depth_uncrt"],
                                       max(item["resolution_x"], item["resolution_y"]),
                                       minimum_ft=200, limit_ft=300)
            if not np.any(eligible):
                continue
            placed = np.zeros((ny, nx), dtype="int16")
            reproject(rasterio.band(character, 1), placed, src_nodata=-128,
                      dst_transform=transform, dst_crs="EPSG:26910", dst_nodata=0,
                      resampling=Resampling.nearest)
            class_counts = classified_counts(placed, eligible)
            counts["fine_supergrids_with_qualified_depth"] += 1
            counts["qualified_depth_cells"] += int(eligible.sum())
            for key, value in class_counts.items():
                counts[key] += value
    if counts["qualified_depth_cells"] != source["counts"]["depth_uncertainty_qualified_200_300ft_cells"]:
        raise ValueError("Original depth cells did not fully intersect the class raster envelope")
    return {"schema_version": 1, "scope": binding["scope"],
            "survey_id": "W00614", "depth_source_url": binding["bag_url"],
            "depth_source_sha256": binding["bag_sha256"],
            "character_source_url": binding["character_url"],
            "character_source_sha256": binding["character_sha256"],
            "depth_datum": "MLLW", "character_native_resolution_m": 2,
            "nominal_depth_band_ft": [200, 300], "counts": counts,
            "fishing_target": False, "exportable": False, "qualified_waypoints": 0,
            "limitation": "No original USGS classified pixels overlap these W00614 depth-screened cells. The character raster's bounding box overlaps, but its valid-data mask does not. A different independent substrate source is needed; no fishing mark, legal or chart clearance follows."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, default=Path("catalog/pigeon-w00614-original-class-binding.json"))
    parser.add_argument("--bag", type=Path, default=Path("var/review/W00614_MB_VR_MLLW_1of1.bag"))
    parser.add_argument("--character", type=Path, default=Path("var/review/SeafloorCharacter_OffshorePigeonPoint.zip"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/data/w00614-pigeon-original-character-overlap.json"))
    args = parser.parse_args()
    binding = json.loads(args.binding.read_text())
    acquire(binding["bag_url"], binding["bag_sha256"], args.bag, 80_000_000, args.fetch)
    acquire(binding["character_url"], binding["character_sha256"], args.character, 10_000_000, args.fetch)
    result = audit(binding, args.bag, args.character)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["counts"])


if __name__ == "__main__":
    main()

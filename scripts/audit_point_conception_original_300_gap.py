#!/usr/bin/env python3
"""Check original Point Conception NOAA BAG cells for 200–300 ft coverage.

This is an exact-file refutation, not a statement about the complete surveys or
the surrounding coast. No fishing geometry is emitted.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import h5py
import numpy as np

from skippercast.platform.bottom_targets import bag_metadata


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "var/review/point-conception-original-bags"
OUTPUT = ROOT / "dist/data/point-conception-original-bag-200-300ft-gap.json"
SOURCES = (
    ("H11952", "H11952_MB_2m_MLLW_2of4.bag",
     "https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11952/BAG/H11952_MB_2m_MLLW_2of4.bag",
     "0cb528795f939e9238e9b11f52279940a2365b2b4b6f52d9f9db8aea82b235fa"),
    ("H11953", "H11953_MB_1m_MLLW_1of4.bag",
     "https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11953/BAG/H11953_MB_1m_MLLW_1of4.bag",
     "4f8a559dffa35ffa0a1eaad1c08f91a138e90e6c041f5e9112ad05670e4713a9"),
)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(path, url, expected):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(url, timeout=90) as response, path.open("wb") as out:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                out.write(chunk)
    if file_sha256(path) != expected:
        raise ValueError(f"Original BAG changed: {path.name}")


def summarize_cells(elevation, uncertainty, *, fill_elevation, fill_uncertainty):
    if elevation.shape != uncertainty.shape:
        raise ValueError("BAG elevation/uncertainty shapes differ")
    valid = (np.isfinite(elevation) & (elevation < 0)
             & (elevation != fill_elevation))
    depths = -elevation[valid]
    valid_uncertainty = (valid & np.isfinite(uncertainty) & (uncertainty > 0)
                         & (uncertainty != fill_uncertainty))
    return {
        "valid_elevation_cells": int(np.count_nonzero(valid)),
        "valid_depth_and_uncertainty_cells": int(np.count_nonzero(valid_uncertainty)),
        "200_to_300ft_depth_cells": int(np.count_nonzero((depths >= 60.96) & (depths <= 91.44))),
        "deeper_than_200ft_cells": int(np.count_nonzero(depths >= 60.96)),
        "minimum_valid_depth_m": float(np.min(depths)) if depths.size else None,
        "maximum_valid_depth_m": float(np.max(depths)) if depths.size else None,
    }


def audit_one(path, survey_id, filename, url, expected):
    if file_sha256(path) != expected:
        raise ValueError(f"Original BAG changed: {filename}")
    with h5py.File(path, "r") as bag:
        root = bag["BAG_root"]
        elevation = root["elevation"]
        uncertainty = root["uncertainty"]
        if elevation.shape != uncertainty.shape or elevation.ndim != 2:
            raise ValueError("Unexpected BAG grid shape")
        xml = root["metadata"][:].tobytes().decode("utf-8").rstrip("\0")
        metadata = bag_metadata(xml, survey_id)
        if metadata["vertical_datum"] != "MLLW" or metadata["uncertainty_type"] != "productUncert":
            raise ValueError("BAG datum or uncertainty meaning changed")
        totals = {key: 0 for key in (
            "valid_elevation_cells", "valid_depth_and_uncertainty_cells",
            "200_to_300ft_depth_cells", "deeper_than_200ft_cells")}
        lows, highs = [], []
        for start in range(0, elevation.shape[0], 256):
            region = np.s_[start:start + 256, :]
            part = summarize_cells(elevation[region], uncertainty[region],
                                   fill_elevation=elevation.fillvalue,
                                   fill_uncertainty=uncertainty.fillvalue)
            for key in totals:
                totals[key] += part[key]
            if part["minimum_valid_depth_m"] is not None:
                lows.append(part["minimum_valid_depth_m"])
                highs.append(part["maximum_valid_depth_m"])
    if not lows or totals["deeper_than_200ft_cells"] != 0:
        raise ValueError("Point Conception exact-file depth refutation changed")
    return {
        "survey_id": survey_id, "file_name": filename, "url": url,
        "sha256": expected, "embedded_metadata_sha256": metadata["metadata_sha256"],
        "survey_dates": [metadata["survey_start"], metadata["survey_end"]],
        "vertical_datum": metadata["vertical_datum"],
        "uncertainty_type": metadata["uncertainty_type"],
        "grid_shape": list(elevation.shape),
        **totals,
        "valid_depth_m_range": [round(min(lows), 3), round(max(highs), 3)],
        "fishing_target": False, "exportable": False,
    }


def build(cache=CACHE):
    sources = [audit_one(cache / name, survey_id, name, url, expected)
               for survey_id, name, url, expected in SOURCES]
    return {
        "schema_version": 1,
        "scope": "point-conception-two-original-noaa-bags-200-300ft-exact-file-gap",
        "sources": sources,
        "combined_200_to_300ft_cells": sum(s["200_to_300ft_depth_cells"] for s in sources),
        "fishing_target": False, "exportable": False,
        "limitations": [
            "Only these two hash-pinned BAG files are checked, not every H11952/H11953 file or every Point Conception survey.",
            "The result does not imply rockfish/lingcod habitat is absent nearby; it removes these exact files as 200–300 ft depth sources.",
            "Original MLLW depth and product-uncertainty metadata do not themselves establish fish, legal access, chart safety or a route.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch:
        for _, name, url, expected in SOURCES:
            fetch(args.cache / name, url, expected)
    report = build(args.cache)
    if args.verify and report != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception original BAG depths changed; review source before reuse")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Checked two original Point Conception BAGs; no 200–300 ft cells in these files")


if __name__ == "__main__":
    main()

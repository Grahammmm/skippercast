#!/usr/bin/env python3
"""Audit every original H11952/H11953 MLLW BAG depth tier, without publishing spots."""

import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from research.scripts.audit_point_conception_original_300_gap import (
    CACHE, ROOT, fetch, file_sha256, summarize_cells,
)
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified


OUTPUT = ROOT / "dist/data/point-conception-original-bag-depth-ladder.json"
SOURCE_HASHES = {
    "H11952": (
        ("H11952_MB_1m_MLLW_1of4.bag", "72f02a82c27110e011c060ff73d9fa9ee77dae7dd058f9b274a606538f4321bd"),
        ("H11952_MB_2m_MLLW_2of4.bag", "0cb528795f939e9238e9b11f52279940a2365b2b4b6f52d9f9db8aea82b235fa"),
        ("H11952_MB_4m_MLLW_3of4.bag", "d3466c6450d083f348e9bcfff0d32d414ce12feee885677ec90790aa1fa3ee48"),
        ("H11952_MB_8m_MLLW_4of4.bag", "7a726128f5d4ee4b5f761f5544d16b2b9e9ddcbe0c80f7bb79573e3659e2afd1"),
    ),
    "H11953": (
        ("H11953_MB_1m_MLLW_1of4.bag", "4f8a559dffa35ffa0a1eaad1c08f91a138e90e6c041f5e9112ad05670e4713a9"),
        ("H11953_MB_2m_MLLW_2of4.bag", "54cb613323fd5d12d38e98d7f265f7bea44025f0e4d0a1de04483679b9bdd94d"),
        ("H11953_MB_4m_MLLW_3of4.bag", "c5f25f47c007f061ae4c7779d8abe41fa1618332c13ec15b35da4fd7f365c208"),
        ("H11953_MB_8m_MLLW_4of4.bag", "e70772d2bbfcb310f7a997f0a58a148baa742b79c242b3f0794d6e5a442b97a2"),
    ),
}


def audit_file(path, survey_id, expected_sha):
    if file_sha256(path) != expected_sha:
        raise ValueError(f"Original BAG changed: {path.name}")
    with h5py.File(path, "r") as bag:
        root = bag["BAG_root"]
        elevation, uncertainty = root["elevation"], root["uncertainty"]
        if elevation.ndim != 2 or elevation.shape != uncertainty.shape:
            raise ValueError("Unexpected BAG elevation/uncertainty grid shape")
        xml = root["metadata"][:].tobytes().decode("utf-8").rstrip("\0")
        metadata = bag_metadata(xml, survey_id)
        if metadata["vertical_datum"] != "MLLW" or metadata["uncertainty_type"] != "productUncert":
            raise ValueError("BAG datum or uncertainty meaning changed")
        totals = {key: 0 for key in (
            "valid_elevation_cells", "valid_depth_and_uncertainty_cells",
            "200_to_300ft_depth_cells", "deeper_than_200ft_cells")}
        preliminary_depth_screen_cells = 0
        native_resolution_m = int(path.name.split("_MB_")[1].split("m_")[0])
        lows, highs = [], []
        for start in range(0, elevation.shape[0], 256):
            section = np.s_[start:start + 256, :]
            part = summarize_cells(elevation[section], uncertainty[section],
                                   fill_elevation=elevation.fillvalue,
                                   fill_uncertainty=uncertainty.fillvalue)
            for key in totals:
                totals[key] += part[key]
            preliminary_depth_screen_cells += int(np.count_nonzero(cells_qualified(
                elevation[section], uncertainty[section], native_resolution_m,
                limit_ft=300, minimum_ft=200, planning_margin_m=2,
                maximum_uncertainty_m=1)))
            if part["minimum_valid_depth_m"] is not None:
                lows.append(part["minimum_valid_depth_m"])
                highs.append(part["maximum_valid_depth_m"])
    if not lows:
        raise ValueError("BAG contains no valid depth cells")
    return {
        "survey_id": survey_id,
        "file_name": path.name,
        "url": f"https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/{survey_id}/BAG/{path.name}",
        "sha256": expected_sha,
        "embedded_metadata_sha256": metadata["metadata_sha256"],
        "survey_dates": [metadata["survey_start"], metadata["survey_end"]],
        "vertical_datum": metadata["vertical_datum"],
        "uncertainty_type": metadata["uncertainty_type"],
        "grid_shape": list(elevation.shape),
        "native_resolution_m": native_resolution_m,
        **totals,
        "preliminary_200_to_300ft_depth_uncertainty_screen_cells": preliminary_depth_screen_cells,
        "valid_depth_m_range": [round(min(lows), 3), round(max(highs), 3)],
        "fishing_target": False,
        "exportable": False,
    }


def build(cache=CACHE):
    sources = [audit_file(cache / name, survey_id, sha)
               for survey_id, files in SOURCE_HASHES.items() for name, sha in files]
    if len(sources) != 8:
        raise ValueError("Incomplete original BAG depth ladder")
    shallow = [row for row in sources if "_1m_" in row["file_name"] or "_2m_" in row["file_name"]]
    deeper = [row for row in sources if "_4m_" in row["file_name"] or "_8m_" in row["file_name"]]
    if (any(row["200_to_300ft_depth_cells"] for row in shallow)
            or any(not row["200_to_300ft_depth_cells"] for row in deeper)):
        raise ValueError("Point Conception original BAG depth-tier finding changed")
    return {
        "schema_version": 1,
        "scope": "point-conception-h11952-h11953-eight-original-mllw-bag-depth-tiers",
        "sources": sources,
        "nominal_200_to_300ft_cells": sum(row["200_to_300ft_depth_cells"] for row in sources),
        "nominal_200_to_300ft_4m_cells": sum(row["200_to_300ft_depth_cells"] for row in deeper if "_4m_" in row["file_name"]),
        "preliminary_4m_depth_uncertainty_screen_cells": sum(
            row["preliminary_200_to_300ft_depth_uncertainty_screen_cells"]
            for row in deeper if row["native_resolution_m"] == 4),
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "Counts are populated native grid cells, not independent fishing patches or survey area; depth tiers have different native resolutions.",
            "These nominal MLLW cells still need full-patch depth-plus-uncertainty, position, habitat, MPA/security, chart and route checks.",
            "The preliminary 4 m count applies only the project's existing per-cell depth, BAG uncertainty and 2 m planning allowance; it does not include spatial or legal clearance.",
            "Survey acquisition is historical; source timestamps and cell counts do not establish present fish or catch probability.",
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
        for survey_id, files in SOURCE_HASHES.items():
            for name, sha in files:
                url = f"https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/{survey_id}/BAG/{name}"
                fetch(args.cache / name, url, sha)
    report = build(args.cache)
    if args.verify and report != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception original BAG ladder changed; review before reuse")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Audited eight original Point Conception BAG tiers; deeper MLLW cells are research leads")


if __name__ == "__main__":
    main()

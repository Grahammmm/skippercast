#!/usr/bin/env python3
"""Hash-pin and inspect all original MLLW VR BAG depth records for two leads.

This refutes *these files* for 200–300 ft bottom targets. It cannot refute
other surveys or substitute for original habitat and chart review.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import h5py
import numpy as np

from skippercast.platform.bottom_targets import bag_metadata


MIN_M, MAX_M = 200 * .3048, 300 * .3048


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire(binding, fetch):
    url = binding["source_url"]
    if (urlsplit(url).scheme != "https" or urlsplit(url).hostname != "data.ngdc.noaa.gov"
            or f"/{binding['survey_id']}/BAG/" not in url
            or not url.endswith(".bag") or not 0 < binding["source_bytes"] <= 100_000_000):
        raise ValueError("Original NOAA BAG binding is invalid")
    path = Path(binding["cache_path"])
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        try:
            with urlopen(Request(url, headers={"User-Agent": "SkipperCast original source review/1.0"}),
                         timeout=90) as response, partial.open("wb") as output:
                if response.status != 200 or response.url != url:
                    raise ValueError("Original NOAA BAG redirected or failed")
                copied = 0
                while block := response.read(1024 * 1024):
                    copied += len(block)
                    if copied > binding["source_bytes"]:
                        raise ValueError("Original NOAA BAG exceeds pinned size")
                    output.write(block)
            if partial.stat().st_size != binding["source_bytes"] or sha256(partial) != binding["source_sha256"]:
                raise ValueError("Downloaded original NOAA BAG changed")
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    if path.stat().st_size != binding["source_bytes"] or sha256(path) != binding["source_sha256"]:
        raise ValueError("Cached original NOAA BAG changed")
    return path


def depth_summary(values):
    valid = np.isfinite(values) & (values < 0) & (values > -3000)
    depth = -values[valid]
    return {"valid_cells": int(valid.sum()),
            "shallowest_depth_m_mllw": round(float(depth.min()), 3) if len(depth) else None,
            "nominal_200_300ft_cells": int(((depth >= MIN_M) & (depth <= MAX_M)).sum()),
            "cells_at_or_shallower_than_300ft": int((depth <= MAX_M).sum())}


def audit_one(binding, path):
    survey = binding["survey_id"]
    with h5py.File(path) as bag:
        root = bag["BAG_root"]
        metadata = bag_metadata(root["metadata"][:].tobytes().decode().rstrip("\0"), survey)
        if (metadata["vertical_datum"] != "MLLW" or metadata["uncertainty_type"] != "productUncert"
                or root["tracking_list"].size or root["varres_tracking_list"].size):
            raise ValueError("Original survey datum, uncertainty or tracking changed")
        overview = depth_summary(root["elevation"][:])
        refinements = root["varres_refinements"]
        if (refinements.ndim != 2 or refinements.shape[0] != 1
                or "depth" not in (refinements.dtype.names or ())):
            raise ValueError("Unexpected original VR refinement layout")
        grids = root["varres_metadata"][:]
        active = (grids["dimensions_x"] > 0) & (grids["dimensions_y"] > 0)
        if not np.any(active):
            raise ValueError("Original VR BAG has no active supergrids")
        starts = grids["index"][active].astype("int64")
        sizes = (grids["dimensions_x"][active].astype("int64") *
                 grids["dimensions_y"][active].astype("int64"))
        order = np.argsort(starts)
        ordered_starts, ordered_sizes = starts[order], sizes[order]
        ends = ordered_starts + ordered_sizes
        used_end = int(ends[-1])
        if (ordered_starts[0] != 0 or np.any(ordered_starts[1:] != ends[:-1])
                or used_end > refinements.shape[1]):
            raise ValueError("Original VR active record ranges are not contiguous")
        parts = []
        for start in range(0, used_end, 500_000):
            parts.append(depth_summary(refinements[0, start:min(start + 500_000, used_end)]["depth"]))
        native = {key: sum(row[key] for row in parts) for key in
                  ("valid_cells", "nominal_200_300ft_cells", "cells_at_or_shallower_than_300ft")}
        native["shallowest_depth_m_mllw"] = min(row["shallowest_depth_m_mllw"] for row in parts
                                                  if row["shallowest_depth_m_mllw"] is not None)
        resolution = np.maximum(grids["resolution_x"][active], grids["resolution_y"][active])
        if (overview["cells_at_or_shallower_than_300ft"] or native["cells_at_or_shallower_than_300ft"]):
            raise ValueError("New <=300 ft original cells require source review")
        return {"survey_id": survey, "source_url": binding["source_url"],
                "source_sha256": binding["source_sha256"], "metadata_sha256": metadata["metadata_sha256"],
                "survey_start": metadata["survey_start"], "survey_end": metadata["survey_end"],
                "vertical_datum": "MLLW", "uncertainty_type": "productUncert",
                "active_supergrids": int(active.sum()), "finest_native_resolution_m": round(float(resolution.min()), 3),
                "active_refinement_records": used_end,
                "trailing_padding_records_ignored": int(refinements.shape[1] - used_end),
                "overview": overview, "native_refinements": native}


def build(binding, fetch=False):
    if (binding.get("scope") != "original-mllw-vr-bags-refuting-central-200-300ft"
            or {s["survey_id"] for s in binding.get("sources", [])} != {"H13152", "W00479"}
            or len(binding["sources"]) != 2):
        raise ValueError("Unexpected original NOAA source set")
    rows = [audit_one(row, acquire(row, fetch)) for row in binding["sources"]]
    return {"schema_version": 1, "scope": binding["scope"],
            "depth_band_ft_mllw": [200, 300], "sources": rows,
            "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
            "limitation": "All original overview and variable-resolution depth records in these two pinned MLLW BAGs are deeper than 300 ft. This is a file-specific depth refutation, not a finding that Point Buchon or the broader sector lacks 200–300 ft habitat."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, default=Path("catalog/central-deep-original-300-bindings.json"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/data/central-deep-original-300-refutation.json"))
    args = parser.parse_args()
    report = build(json.loads(args.binding.read_text()), args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print([(row["survey_id"], row["native_refinements"]["shallowest_depth_m_mllw"])
           for row in report["sources"]])


if __name__ == "__main__":
    main()

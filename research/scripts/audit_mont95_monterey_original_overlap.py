#!/usr/bin/env python3
"""Audit original 1995 USGS multibeam cells against Monterey research outlines.

This is a source-discovery audit, not depth qualification or a fishing layer.
The 1995 grid has no documented vertical datum or upper accuracy bound.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

import numpy as np
import rasterio
from rasterio.mask import mask
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from research.scripts.audit_usgs_monterey_300_paired import original_tiff


ROOT = Path(__file__).resolve().parents[2]
BASE = "https://pubs.usgs.gov/of/2001/0179/data/battopo/"
NEWER_URL = "https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/data/Bathymetry_2m_OffshoreMonterey.zip"
NEWER_SHA256 = "2a769bc2bb343f6df5041ad7cab7bfcfe3eb641e2ef0bba7f3709edcd07c17f1"
FILES = {
    "mont95.txt": "581df812be8931ea5ba5c25fe2a130d00b89b178152d25d3e03dfd871d079e4e",
    "mont95ng/dblbnd.adf": "f1af55a10ba07301ed12334ecd4b1bfc743f57c36aefdbbd77c07c43322576d2",
    "mont95ng/hdr.adf": "1bd9d4a6452c2a7a7e3897827fcded6740317690b19478140ffb67d83545d627",
    "mont95ng/log": "9a3f836764333f5d29c8494f18979cf3be4bb0f00b0868a802fa97ec2f5d0089",
    "mont95ng/prj.adf": "dc0f7bcf5cc4d38869512256e57f044e34b913fc6b5618476504a4ffaca198e2",
    "mont95ng/sta.adf": "db42b5b2380fdcbb4567260da509810036e8d1c317261852e8105db1537eb8a7",
    "mont95ng/w001001.adf": "116508796cc9f0789abb8e66d364cad4ae0d6f03c3400e6fbcc739804f4c2f9c",
    "mont95ng/w001001x.adf": "da51a0c4ce03b767b591ee92e78349aaec249b1bc05e6985e3a7520d0bd778ac",
    "mont95sg/dblbnd.adf": "5951d30f4be38864534200bb1787149dce040fa18cbbab3d500c2aaa5f96e46b",
    "mont95sg/hdr.adf": "35cb89d429bf3b5303c3e6bd21fd690128bf350ad3ee41aa552876720a9f24c0",
    "mont95sg/log": "60083bd745f40562e9d090be2a3ca9a3a7da81d25ce270961fb80a5af209cbfe",
    "mont95sg/prj.adf": "dc0f7bcf5cc4d38869512256e57f044e34b913fc6b5618476504a4ffaca198e2",
    "mont95sg/sta.adf": "d29854d65cebe836fb4c09c2d3fc1e46333d0bd8828a670d98f0ced885b6eb70",
    "mont95sg/vat.adf": "40ad3b32fc59ceb955246155be5f75d24f7614607b6294ee061d69a6ea81af1a",
    "mont95sg/w001001.adf": "ba1903dc6b0d1a7af8b3a86bab67df8485fd9024ae5b28239173ac37449aed8c",
    "mont95sg/w001001x.adf": "336894e304741eb7f6857cab4cef954db21c448cd2298e9ab97ccc8a8d322dd0",
}


def verify_sources(cache, fetch=False):
    for name, expected in FILES.items():
        path = cache / name
        if fetch:
            path.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(BASE + name, headers={"User-Agent": "SkipperCast-source-audit/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read(30_000_001)
            if len(data) > 30_000_000:
                raise ValueError(f"Oversized original source: {name}")
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"Original source bytes changed: {name}")
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Original source bytes changed: {name}")
    metadata = (cache / "mont95.txt").read_text()
    for phrase in ("Simrad EM1000", "in 1995", "resolution of 5 m", "records depth as negative"):
        if phrase not in metadata:
            raise ValueError(f"Original metadata changed: {phrase}")


def rounded(value):
    return round(float(value), 3)


def ensure_newer(root, fetch=False):
    newer = root / "var/review/Bathymetry_2m_OffshoreMonterey.zip"
    if fetch and not newer.exists():
        newer.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(NEWER_URL, headers={"User-Agent": "SkipperCast-source-audit/1.0"})
        with urllib.request.urlopen(request, timeout=300) as response:
            data = response.read(250_000_001)
        if len(data) > 250_000_000 or hashlib.sha256(data).hexdigest() != NEWER_SHA256:
            raise ValueError("Recent original USGS archive changed or oversized")
        newer.write_bytes(data)
    if hashlib.sha256(newer.read_bytes()).hexdigest() != NEWER_SHA256:
        raise ValueError("Recent original USGS archive changed")
    return newer


def audit(root, fetch=False):
    cache = root / "var/review/mont95-original"
    verify_sources(cache, fetch)
    matrix_path = root / "dist/data/monterey-300-source-evidence-matrix.json"
    context_path = root / "dist/data/usgs-offshore-monterey-hard-context.geojson"
    newer = ensure_newer(root, fetch)
    matrix = json.loads(matrix_path.read_text())
    context = json.loads(context_path.read_text())
    if matrix.get("outline_count") != 17 or len(matrix["review_order"]) != 17:
        raise ValueError("Reviewed Monterey outline set changed")
    features = {f["properties"]["id"]: f for f in context["features"]}
    rows = []
    with rasterio.open(original_tiff(newer)) as recent:
        if str(recent.crs) != "EPSG:26910" or any(abs(r - 2) > .01 for r in recent.res):
            raise ValueError("Recent USGS source grid changed")
        for item in matrix["review_order"]:
            ident = item["context_id"]
            geometry = shape(features[ident]["geometry"])
            for name in ("mont95ng", "mont95sg"):
                with rasterio.open(cache / name) as original:
                    if str(original.crs) != "EPSG:26910" or any(abs(r - 5) > .01 for r in original.res):
                        raise ValueError(f"Original {name} reference frame or spacing changed")
                    project = Transformer.from_crs("EPSG:4326", original.crs, always_xy=True).transform
                    polygon = transform(project, geometry)
                    if not polygon.intersects(box(*original.bounds)):
                        continue
                    samples, window_transform = mask(original, [mapping(polygon)], crop=True, filled=False)
                    values = samples[0]
                    valid = ~np.ma.getmaskarray(values) & np.isfinite(np.ma.getdata(values))
                    if not np.any(valid):
                        continue
                    row_index, col_index = np.nonzero(valid)
                    heights = np.ma.getdata(values)[valid].astype(float)
                    band = (heights <= -60.96) & (heights >= -91.44)
                    xs, ys = rasterio.transform.xy(window_transform, row_index, col_index)
                    recent_samples = np.array([v[0] for v in recent.sample(zip(xs, ys), masked=True)], dtype=float)
                    paired = np.isfinite(recent_samples) & (recent_samples != recent.nodata)
                    delta = recent_samples[paired] - heights[paired]
                    rows.append({
                        "context_id": ident, "original_grid": name,
                        "original_valid_5m_cells": int(valid.sum()),
                        "original_nominal_200_300ft_cells_unknown_datum": int(band.sum()),
                        "paired_2016_cells": int(paired.sum()),
                        "recent_minus_1995_median_m": rounded(np.median(delta)) if len(delta) else None,
                        "recent_minus_1995_p90_abs_m": rounded(np.percentile(np.abs(delta), 90)) if len(delta) else None,
                        "large_difference_over_5m": bool(len(delta) and np.median(np.abs(delta)) > 5),
                    })
    covered = {row["context_id"] for row in rows}
    camera = {item["context_id"] for item in matrix["review_order"] if item["historical_rockfish_positive_windows"] > 0}
    return {
        "schema_version": 1, "scope": "monterey-1995-original-multibeam-research-overlap",
        "source_urls": {name: BASE + name for name in FILES}, "source_sha256": FILES,
        "newer_usgs_archive_sha256": hashlib.sha256(newer.read_bytes()).hexdigest(),
        "review_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "research_context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "survey_year": 1995, "original_grid_spacing_m": 5,
        "original_vertical_datum_documented": False,
        "original_upper_vertical_error_documented": False,
        "independence_from_2016_composite_established": False,
        "outlines_reviewed": 17, "outlines_with_original_cells": len(covered),
        "rockfish_camera_positive_outlines_with_original_cells": len(camera & covered),
        "outlines": rows, "fishing_target": False, "exportable": False,
        "limitations": [
            "The 1995 ArcInfo grids have no stated vertical datum or defensible upper vertical-error bound; nominal depth bands cannot be used as 300 ft release tests.",
            "The paired difference is not total propagated uncertainty, chart-datum conversion, or evidence of survey independence; source reuse, offsets, terrain change and registration remain unresolved.",
            "Large paired discrepancies require separate original-line review; do not average them into a tolerance.",
            "Old 5 m cells and a later 2 m composite do not establish species presence, current habitat, MPA access or a fishing waypoint.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/data/monterey-1995-original-multibeam-overlap.json"))
    args = parser.parse_args()
    report = audit(args.root.resolve(), args.fetch)
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if report != {key: value for key, value in saved.items() if key != "checked_at"}:
            raise ValueError("1995 original-cell comparison changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"1995 original grid covers {report['outlines_with_original_cells']}/17 research outlines; zero fishing targets")


if __name__ == "__main__":
    main()

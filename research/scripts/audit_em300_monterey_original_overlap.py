#!/usr/bin/env python3
"""Read 1998 USGS EM300 original grid cells at Monterey research outlines.

This audit compares source elevations, not survey accuracy, independence,
legal fishing depth or verified fish habitat. It publishes aggregates only.
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
from research.scripts.audit_mont95_monterey_original_overlap import NEWER_SHA256, ensure_newer, rounded


ROOT = Path(__file__).resolve().parents[2]
BASE = "https://pubs.usgs.gov/of/2001/0179/data/battopo/"
FILES = {
    "em300bat.txt": "6a67db6a766fc9df85f7be68054408b8b5140bf6362a44b56813b5f7a0e1a4ed",
    "mtshlf5g/dblbnd.adf": "36416887ff74d890ec95f8a0a58f6cd1c233717b464577a9fd2db9d130307ed4",
    "mtshlf5g/hdr.adf": "8c4e39e8dd351345debe3203d46af43a388f66383b1fa60244805b0e2599c947",
    "mtshlf5g/log": "a11aae03ef9151e7073dabb29d408021cdeb66edc5e3edc813482bf8d6aa8287",
    "mtshlf5g/prj.adf": "b8129ca2a424f114e05c6efbb27c75d87e1b94cc6538dbe531b75ecdee4128d2",
    "mtshlf5g/sta.adf": "d07d24f4ccb49aacda4bc573b8c428c7fc5974932e1033fe8b867f10d9d49629",
    "mtshlf5g/w001001.adf": "0e55bf222031a63afebadb23ec8963e7bca7bb76e057fa544fe2d017421d3b81",
    "mtshlf5g/w001001x.adf": "04fa6592ec1c71b1858b5c59616493abefd7cf6826c1e1749416451d6ec06434",
    "sgf5g/dblbnd.adf": "8ca47f7da187e8bef7f62d24560a977707f658c476041134f250d6e9e1798cf7",
    "sgf5g/hdr.adf": "2ff995707c8c96447725e6924e17e5df4f0504a9010c06ae8a221196ba20a9b1",
    "sgf5g/log": "4a546106f5a6fa27f00461076ec412e6858c2563461ac93672be173e950443c2",
    "sgf5g/prj.adf": "b8129ca2a424f114e05c6efbb27c75d87e1b94cc6538dbe531b75ecdee4128d2",
    "sgf5g/sta.adf": "91575c7645763452b7b0c4a384265538bb7d8228c3cc34d8d3b3aeeb40a46399",
    "sgf5g/w001001.adf": "b9d19e4964e33224c73741c9a26342e830ca8c753eaa96ca49cc1eaad74429c9",
    "sgf5g/w001001x.adf": "93a85210a21ff99134823d02104e85c73418958b51bd56260d62e9963fe8e5fa",
}


def verify(cache, fetch):
    for name, expected in FILES.items():
        path = cache / name
        if fetch:
            request = urllib.request.Request(BASE + name, headers={"User-Agent": "SkipperCast-source-audit/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read(55_000_001)
            if len(data) > 55_000_000 or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"Official EM300 source changed or oversized: {name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Official EM300 source changed: {name}")
    metadata = (cache / "em300bat.txt").read_text()
    for phrase in ("in 1998", "MTSHLF5G", "SGF5G", "resolution of 5 m", "not intended for navigational purposes"):
        if phrase not in metadata:
            raise ValueError(f"EM300 metadata changed: {phrase}")


def build(root, fetch=False):
    cache = root / "var/review/em300-original"
    verify(cache, fetch)
    recent_path = ensure_newer(root, fetch)
    matrix_path = root / "dist/data/monterey-300-source-evidence-matrix.json"
    context_path = root / "dist/data/usgs-offshore-monterey-hard-context.geojson"
    old_receipt_path = root / "dist/data/monterey-1995-original-multibeam-overlap.json"
    matrix = json.loads(matrix_path.read_text())
    context = json.loads(context_path.read_text())
    old_receipt = json.loads(old_receipt_path.read_text())
    if (matrix.get("outline_count") != 17
            or old_receipt.get("scope") != "monterey-1995-original-multibeam-research-overlap"):
        raise ValueError("Reviewed Monterey research set changed")
    features = {f["properties"]["id"]: f for f in context["features"]}
    rows = []
    with rasterio.open(original_tiff(recent_path)) as recent:
        if str(recent.crs) != "EPSG:26910":
            raise ValueError("Later source reference frame changed")
        for grid_name in ("mtshlf5g", "sgf5g"):
            with rasterio.open(cache / grid_name) as old:
                if str(old.crs) != "EPSG:26910" or any(abs(v - 5) > .01 for v in old.res):
                    raise ValueError(f"Original {grid_name} reference frame or spacing changed")
                project = Transformer.from_crs("EPSG:4326", old.crs, always_xy=True).transform
                for item in matrix["review_order"]:
                    ident = item["context_id"]
                    polygon = transform(project, shape(features[ident]["geometry"]))
                    if not polygon.intersects(box(*old.bounds)):
                        continue
                    pixels, affine = mask(old, [mapping(polygon)], crop=True, filled=False)
                    values = pixels[0]
                    good = ~np.ma.getmaskarray(values) & np.isfinite(np.ma.getdata(values))
                    if not np.any(good):
                        continue
                    index_rows, index_cols = np.nonzero(good)
                    heights = np.ma.getdata(values)[good].astype(float)
                    xs, ys = rasterio.transform.xy(affine, index_rows, index_cols)
                    samples = np.array([v[0] for v in recent.sample(zip(xs, ys), masked=True)], dtype=float)
                    paired = np.isfinite(samples) & (samples != recent.nodata)
                    delta = samples[paired] - heights[paired]
                    if not len(delta):
                        raise ValueError(f"No later source pairing for {ident}")
                    rows.append({
                        "context_id": ident, "original_grid": grid_name,
                        "original_valid_5m_cells": int(good.sum()),
                        "original_min_elevation_m_unknown_datum": rounded(np.min(heights)),
                        "original_max_elevation_m_unknown_datum": rounded(np.max(heights)),
                        "original_nominal_200_300ft_cells_unknown_datum": int(((heights <= -60.96) & (heights >= -91.44)).sum()),
                        "paired_2016_cells": int(paired.sum()),
                        "recent_minus_1998_median_m": rounded(np.median(delta)),
                        "recent_minus_1998_p90_abs_m": rounded(np.percentile(np.abs(delta), 90)),
                        "historical_rockfish_positive_windows": item["historical_rockfish_positive_windows"],
                    })
    covered = {row["context_id"] for row in rows}
    camera = {item["context_id"] for item in matrix["review_order"] if item["historical_rockfish_positive_windows"]}
    target_001 = next(row for row in rows if row["context_id"].endswith("-001"))
    target_001_matrix = next(row for row in matrix["review_order"] if row["context_id"].endswith("-001"))
    old_040 = next(row for row in old_receipt["outlines"] if row["context_id"].endswith("-040"))
    new_040 = next(row for row in rows if row["context_id"].endswith("-040"))
    return {
        "schema_version": 1, "scope": "monterey-1998-original-em300-research-overlap",
        "source_urls": {name: BASE + name for name in FILES}, "source_sha256": FILES,
        "newer_usgs_archive_sha256": NEWER_SHA256,
        "research_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "research_context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "older_1995_receipt_sha256": hashlib.sha256(old_receipt_path.read_bytes()).hexdigest(),
        "survey_year": 1998, "original_grid_spacing_m": 5,
        "original_vertical_datum_documented": False,
        "original_upper_vertical_error_documented": False,
        "independence_from_2016_composite_established": False,
        "outlines_reviewed": 17, "outlines_with_original_cells": len(covered),
        "rockfish_camera_positive_outlines_with_original_cells": len(camera & covered),
        "previously_uncovered_camera_outline_001": {
            "populated_cells": target_001["original_valid_5m_cells"],
            "nominal_200_300ft_cells_unknown_datum": target_001["original_nominal_200_300ft_cells_unknown_datum"],
            "original_elevation_range_m_unknown_datum": [target_001["original_min_elevation_m_unknown_datum"], target_001["original_max_elevation_m_unknown_datum"]],
            "existing_mpa_or_gea_review_hold": target_001_matrix["mapped_protected_area_or_gea_buffer"],
            "existing_enc_danger_review_hold": target_001_matrix["mapped_enc_danger_buffer"],
        },
        "outline_040_disagreement_followup": {
            "recent_minus_1995_median_m": old_040["recent_minus_1995_median_m"],
            "recent_minus_1998_median_m": new_040["recent_minus_1998_median_m"],
        },
        "outlines": rows, "fishing_target": False, "exportable": False,
        "limitations": [
            "The 1998 EM300 archive gives NAD83 5 m grids but no vertical datum or conservative upper depth error; a nominal depth band cannot establish the 300 ft MLLW limit.",
            "Paired differences are not propagated uncertainty or proof that the 1998 and 2016 products are independent; the composite may reuse the earlier survey.",
            "The formerly uncovered camera outline has populated older cells, but none falls in the nominal 200–300 ft interval in this unknown datum.",
            "That camera outline also intersects the current bounded MPA/ENC danger research screens; historical depth data cannot clear legal or chart access.",
            "The 1995 versus 1998 disagreement at outline 040 needs original survey-line, tide and registration review; neither raster is assumed correct by proximity to the composite.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/data/monterey-1998-original-em300-overlap.json"))
    args = parser.parse_args()
    report = build(args.root.resolve(), args.fetch)
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if report != {key: value for key, value in saved.items() if key != "checked_at"}:
            raise ValueError("1998 original EM300 comparison changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"1998 EM300 covers {report['outlines_with_original_cells']}/17 outlines; zero fishing targets")


if __name__ == "__main__":
    main()

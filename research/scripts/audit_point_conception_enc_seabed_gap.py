#!/usr/bin/env python3
"""Check official ENC seabed features at two original Point Conception patches.

This is a bounded negative/positive chart-feature discovery receipt, never an
independent camera survey or a fishing-location release.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import Resampling, reproject
from scipy.ndimage import binary_erosion, label
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from research.lib.paths import ROOT

from research.scripts.audit_point_conception_original_300_gap import CACHE, file_sha256
from research.scripts.audit_point_conception_original_300_ladder import SOURCE_HASHES
from research.scripts.audit_point_conception_4m_hard_overlap import USGS_CACHE, USGS_SOURCE, source_tif
from research.scripts.refresh_enc_hazards import BASE, SERVICES, fetch_json, query_layer
from skippercast.platform.contracts import atomic_json


OUTPUT = ROOT / "research/receipts/point-conception-original-4m-enc-seabed-gap.json"
PRIOR = ROOT / "dist/data/point-conception-original-4m-patch-robustness.json"
SEABED_SUFFIXES = ("Seabed_Area_point", "Seabed_Area_line", "Seabed_Area")


def original_patches(prior: dict) -> list[tuple[str, object]]:
    if (prior.get("scope") != "point-conception-original-4m-class3-patch-depth-boundary-sensitivity"
            or prior.get("fishing_target") is not False
            or [row["eight_meter_inset_patches"][0]["native_cells"] for row in prior["rows"]] != [296, 226]):
        raise ValueError("Original 4 m patch baseline changed")
    name, _, expected_class_sha = USGS_SOURCE
    archive = USGS_CACHE / name
    if file_sha256(archive) != expected_class_sha:
        raise ValueError("Original USGS class archive changed")
    patches = []
    with rasterio.open(source_tif(archive)) as source:
        read = source.read(1, masked=True)
        character = np.where(np.ma.getmaskarray(read), 0, read.data).astype("uint8")
        for files in SOURCE_HASHES.values():
            for bag_name, expected_bag_sha in files:
                if "_4m_" not in bag_name:
                    continue
                path = CACHE / bag_name
                if file_sha256(path) != expected_bag_sha:
                    raise ValueError("Original NOAA BAG changed")
                with rasterio.open(path) as bag:
                    elevation, uncertainty = bag.read(1), bag.read(2)
                    classes = np.zeros(elevation.shape, dtype="uint8")
                    reproject(character, classes, src_transform=source.transform,
                              src_crs=source.crs, src_nodata=0,
                              dst_transform=bag.transform, dst_crs="EPSG:26910",
                              dst_nodata=0, resampling=Resampling.nearest)
                    eligible = (np.isfinite(elevation) & np.isfinite(uncertainty)
                                & (elevation < 0) & (uncertainty > 0) & (uncertainty <= 1)
                                & (-elevation >= 60.96)
                                & (-elevation + uncertainty + 2 <= 91.44))
                    labels, _ = label(eligible & binary_erosion(classes % 10 == 3,
                                                                  iterations=2, border_value=0))
                    sizes = np.bincount(labels.ravel())[1:]
                    retained = np.flatnonzero(sizes * 16 >= 2500) + 1
                    if len(retained) != 1:
                        raise ValueError("Reviewed Point Conception component count changed")
                    component = labels == retained[0]
                    polygon = shape(next(geometry for geometry, value in
                                         shapes(component.astype("uint8"), mask=component,
                                                transform=bag.transform) if value == 1))
                    if abs(polygon.area - int(sizes[retained[0] - 1]) * 16) > 0.01:
                        raise ValueError("Original patch geometry area changed")
                    patches.append((bag_name[:6], polygon))
    if [survey for survey, _ in patches] != ["H11952", "H11953"]:
        raise ValueError("Expected two original survey patches")
    return patches


def query_one(args):
    survey, bounds, service, layer_name, layer_id = args
    features, receipt = query_layer(service, layer_name, layer_id, bounds)
    return {"survey_id": survey, "service": service, "layer": layer_name,
            "layer_id": layer_id, "count_within_100m_envelope": len(features),
            "count_response_sha256": receipt["count_sha256"],
            "feature_response_sha256": receipt["data_sha256"]}


def build(prior: dict, *, fetch=fetch_json, query=query_one) -> dict:
    patches = original_patches(prior)
    to_geo = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True).transform
    layers = []
    metadata_hashes = {}
    for service in SERVICES:
        metadata, digest = fetch(f"{BASE}/{service}/MapServer?f=pjson")
        metadata_hashes[service] = digest
        matches = [(row["name"].split(".")[-1], row["id"])
                   for row in metadata.get("layers", [])
                   if any(row["name"].endswith(suffix) for suffix in SEABED_SUFFIXES)]
        if len(matches) not in (2, 3) or len({name for name, _ in matches}) != len(matches):
            raise ValueError("NOAA ENC seabed layer inventory changed")
        layers.extend((service, name, layer_id) for name, layer_id in matches)
    if len(layers) != 8:
        raise ValueError("Expected eight NOAA ENC seabed layers")
    jobs = []
    for survey, polygon in patches:
        # Use a 100 m *projected* review radius before requesting an envelope.
        bounds = transform(to_geo, polygon.buffer(100)).bounds
        for service, name, layer_id in layers:
            jobs.append((survey, bounds, service, name, layer_id))
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(query, jobs))
    by_survey = {survey: [row for row in rows if row["survey_id"] == survey]
                 for survey, _ in patches}
    return {
        "schema_version": 1,
        "scope": "point-conception-two-original-4m-patches-enc-seabed-feature-gap",
        "source": BASE,
        "original_surveys": ["H11952", "H11953"],
        "query_radius_m": 100,
        "reviewed_scale_bands": list(SERVICES),
        "source_metadata_sha256": metadata_hashes,
        "by_survey": {survey: {
            "queried_layers": len(items),
            "charted_seabed_features_in_100m_envelope": sum(x["count_within_100m_envelope"] for x in items),
            "layer_receipts": [{k: v for k, v in item.items() if k != "survey_id"} for item in items],
        } for survey, items in by_survey.items()},
        "independent_bottom_verified": False,
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "The query is limited to NOAA ENC Direct seabed point, line and area feature layers at three chart scale bands and a 100 m envelope around each private research component.",
            "An empty chart layer does not show absence of rock or fish, nor prove that the ENC covers a seabed sample at candidate scale.",
            "A charted seabed feature, if later found, may derive from the same sonar survey and is not independent camera or grab groundtruth.",
            "Exact component geometry and query URLs are private; this aggregate receipt does not clear chart hazards, legal access, drift paths, or fishing rank.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, default=PRIOR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = build(json.loads(args.prior.read_text()))
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception ENC seabed feature status changed; review before use")
    atomic_json(args.output, result)
    print(json.dumps({survey: x["charted_seabed_features_in_100m_envelope"]
                      for survey, x in result["by_survey"].items()}))


if __name__ == "__main__":
    main()

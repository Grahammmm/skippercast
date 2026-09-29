#!/usr/bin/env python3
"""Pin source processing and actual BAG cell ranges for two held research patches."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
import zipfile

import h5py
import numpy as np
from pypdf import PdfReader
import rasterio
from rasterio.features import geometry_mask

from research.scripts.audit_point_conception_4m_access import candidate_footprints
from research.scripts.audit_point_conception_4m_hard_overlap import USGS_CACHE, USGS_SOURCE
from research.lib.paths import ROOT
from research.scripts.audit_point_conception_original_300_gap import CACHE, file_sha256
from research.scripts.audit_point_conception_original_300_ladder import SOURCE_HASHES


OUTPUT = ROOT / "research/receipts/point-conception-original-4m-source-lineage.json"
USGS_PAMPHLET_URL = "https://pubs.usgs.gov/of/2018/1024/ofr20181024_pamphlet.pdf"
USGS_PAMPHLET_SHA = "a1e2913c78a8a0b89f213acff8844cab9baba481a83c2d3b04bd2f68bf66a009"
REPORT_HASHES = {
    "H11952": "387941c7238f10b6477d8e92de01187c0d9f153fb3f36b2d8f8d65fca820b086",
    "H11953": "b6cfc4a13417be089319ee96c5f5a955a79db212e0961bc846cab1f9e8492fb5",
}


def report_path(cache, survey, *, fetch):
    path = cache / f"{survey}-DR.pdf"
    url = f"https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/{survey}/DR/{survey}.pdf"
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        with urlopen(Request(url, headers={"User-Agent": "SkipperCast source review/1.0"}), timeout=30) as response:
            if response.url != url:
                raise ValueError("Unexpected NOAA report redirect")
            raw = response.read(10_000_001)
        if len(raw) > 10_000_000:
            raise ValueError("NOAA report exceeds review size limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    if file_sha256(path) != REPORT_HASHES[survey]:
        raise ValueError(f"NOAA original report changed: {survey}")
    return path, url


def report_control(path, survey):
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(path).pages).lower()
    required = (
        "fugro pelagos",
        f"80-100 meters: 4 m resolution, name “{survey.lower()}_4m”",
        "the horizontal control datum for this survey was the north american datum of 1983 (nad83)",
        "final positioning, however, was don e using post-processed kinema tic (ppk) methods",
        "final tidal corrections were generated using ppk processing methods in conjunction with noaa’s vdatum model",
        "vdatum nad83 to mllw offset grid to produce mllw tide correctors",
    )
    missing = [phrase for phrase in required if phrase not in text]
    if missing:
        raise ValueError(f"NOAA source processing text changed: {survey}: {missing}")
    return {
        "horizontal_datum_reported": "NAD83",
        "final_positioning": "PPK",
        "sounding_datum": "MLLW",
        "datum_process": "PPK + NOAA VDatum NAD83-to-MLLW offset grid in CARIS GPSTide",
        "historical_fieldsheet_4m_depth_range_m_reported": [80, 100],
        "caveat": "The report's historical 4 m fieldsheet tier is not assumed identical to the later downloadable MB_4m BAG band. Actual patch cells are shallower than 80 m. The report does not quantify USGS-to-NOAA horizontal registration.",
    }


def bag_lineage(path, survey):
    with h5py.File(path) as bag:
        raw = bag["BAG_root/metadata"][()].tobytes()
    text = raw.decode("utf-8", "replace")
    title = re.search(r"<gmd:title><gco:CharacterString>([^<]+)</gco:CharacterString>", text)
    stamp = re.search(r"<gmd:dateStamp><gco:Date>([^<]+)</gco:Date>", text)
    if (not title or title.group(1) != f"{survey}_MB_4m_MLLW_3of4_Final.csar"
            or not stamp or not stamp.group(1).startswith("2022-")
            or "Mean Lower Low Water" not in text
            or 'codeListValue="productUncert"' not in text
            or f"/{survey}/Processed_Public/CARIS/HDCS_DATA/" not in text
            or "CreateHIPSGridWithCUBE" not in text):
        raise ValueError(f"Original BAG product lineage changed: {survey}")
    return {
        "embedded_metadata_sha256": hashlib.sha256(raw).hexdigest(),
        "published_product_title": title.group(1),
        "metadata_stamp": stamp.group(1),
        "embedded_vertical_datum": "MLLW",
        "embedded_uncertainty_type": "productUncert",
        "input_lineage": "Survey-specific CARIS HIPS processed-public lines; CUBE grid process",
        "tier_caveat": "This published MB_4m BAG contains 61–73 m patch cells, outside the report's 80–100 m historical fieldsheet tier. Treat the report as survey-level control provenance, not a one-to-one grid-band crosswalk.",
    }


def usgs_class_lineage(archive):
    if file_sha256(archive) != USGS_SOURCE[2]:
        raise ValueError("Original USGS character archive changed")
    with zipfile.ZipFile(archive) as bundle:
        member = next(name for name in bundle.namelist() if name.endswith("_metadata.txt"))
        raw = bundle.read(member)
    text = " ".join(raw.decode("utf-8", "replace").lower().split())
    required = (
        "video-supervised maximum likelihood classification of the bathymetry and intensity of return from sonar systems",
        "backscatter intensity and derivative rugosity",
        "signatures defined by hand-drawn polygons located through sediment samples and video-observation ground truthing",
    )
    if any(phrase not in text for phrase in required):
        raise ValueError("USGS original class method changed")
    return {
        "source_url": USGS_SOURCE[1],
        "source_sha256": USGS_SOURCE[2],
        "metadata_member_sha256": hashlib.sha256(raw).hexdigest(),
        "method": "Video-supervised maximum-likelihood classification of bathymetry-derived rugosity and sonar backscatter, with hand-drawn training polygons tied to samples and video.",
        "source_independence_from_noaa_bag": "not established; both products may reuse 2008 Fugro acoustic soundings",
        "independent_patch_bottom_observations": 0,
        "accuracy_note": "Qualitative map QC and instrument-position text do not supply a patch-scale confusion matrix or achieved USGS-to-NOAA registration bound.",
    }


def usgs_acoustic_source(path, *, fetch):
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        with urlopen(Request(USGS_PAMPHLET_URL, headers={"User-Agent": "SkipperCast source review/1.0"}), timeout=30) as response:
            if response.url != USGS_PAMPHLET_URL:
                raise ValueError("Unexpected USGS report redirect")
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("USGS report exceeds review size limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    if file_sha256(path) != USGS_PAMPHLET_SHA:
        raise ValueError("USGS source report changed")
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(path).pages).lower()
    if "bathymetry and backscatter data collected by fugro pelagos" not in text or "in 2008" not in text:
        raise ValueError("USGS original acoustic-source statement changed")
    return {
        "source_url": USGS_PAMPHLET_URL,
        "source_sha256": USGS_PAMPHLET_SHA,
        "reported_acoustic_source": "Fugro Pelagos bathymetry and backscatter collected in 2008",
        "comparison": "NOAA H11952/H11953 are also 2008 Fugro surveys. Exact line/pixel lineage between USGS class and the BAGs is not proven; do not count them as independent acoustics.",
    }


def audit(bag_cache, usgs_cache, report_cache, *, fetch=False):
    prior = json.loads((ROOT / "dist/data/point-conception-original-4m-rugged-overlap.json").read_text())
    camera = json.loads((ROOT / "research/receipts/point-conception-original-4m-camera-gap.json").read_text())
    if any(row["bottom_observations_inside_component"] for row in camera["components"]):
        raise ValueError("Direct camera evidence changed; review before asserting a gap")
    candidates = candidate_footprints(bag_cache, usgs_cache, prior)
    rows = []
    for survey, cells, footprint in candidates:
        pdf, url = report_path(report_cache, survey, fetch=fetch)
        bag_name, bag_sha = next(item for item in SOURCE_HASHES[survey] if "_4m_" in item[0])
        bag_path = bag_cache / bag_name
        if file_sha256(bag_path) != bag_sha:
            raise ValueError(f"Original BAG changed: {survey}")
        with rasterio.open(bag_path) as bag:
            cell_mask = geometry_mask([footprint], out_shape=bag.shape,
                                      transform=bag.transform, invert=True)
            if int(cell_mask.sum()) != cells:
                raise ValueError("Research component no longer matches original cells")
            depth = -bag.read(1)[cell_mask]
            uncertainty = bag.read(2)[cell_mask]
        if (not np.all(np.isfinite(depth)) or not np.all(np.isfinite(uncertainty))
                or np.any(uncertainty <= 0)):
            raise ValueError("Invalid original depth or uncertainty cell")
        rows.append({
            "survey_id": survey,
            "original_bag_sha256": bag_sha,
            "original_bag_metadata": bag_lineage(bag_path, survey),
            "original_report_url": url,
            "original_report_sha256": REPORT_HASHES[survey],
            "survey_processing": report_control(pdf, survey),
            "native_cells": cells,
            "native_resolution_m": 4,
            "measured_depth_mllw_m": {"minimum": round(float(depth.min()), 3),
                                      "median": round(float(np.median(depth)), 3),
                                      "maximum": round(float(depth.max()), 3)},
            "bag_supplied_uncertainty_m": {"minimum": round(float(uncertainty.min()), 3),
                                           "median": round(float(np.median(uncertainty)), 3),
                                           "maximum": round(float(uncertainty.max()), 3)},
            "maximum_depth_plus_uncertainty_and_2m_planning_margin_m": round(float((depth + uncertainty + 2).max()), 3),
            "fishing_target": False,
            "exportable": False,
        })
    return {
        "schema_version": 1,
        "scope": "point-conception-two-original-4m-patches-noaa-usgs-lineage",
        "usgs_character": usgs_class_lineage(usgs_cache / USGS_SOURCE[0]),
        "usgs_map_report": usgs_acoustic_source(usgs_cache / "ofr20181024_pamphlet.pdf", fetch=fetch),
        "components": rows,
        "camera_gap_receipt": "dist/data/point-conception-original-4m-camera-gap.json",
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "The original NOAA BAG already contains MLLW depths and supplied uncertainty; reapplying VDatum to the BAG would double-transform it.",
            "BAG cell uncertainty is not a measured bound on NOAA-to-USGS horizontal registration or habitat-class error.",
            "The 2 m addition is a SkipperCast planning margin, not a NOAA uncertainty statistic.",
            "The USGS interpreted hard/rugged class is not an independent acoustic survey or direct camera confirmation at either patch.",
            "Trip-date security, species rules, full chart/routes and current fish evidence remain unverified.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag-cache", type=Path, default=CACHE)
    parser.add_argument("--usgs-cache", type=Path, default=USGS_CACHE)
    parser.add_argument("--report-cache", type=Path, default=CACHE)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = audit(args.bag_cache, args.usgs_cache, args.report_cache, fetch=args.fetch)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception source lineage changed; hold for review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"components": len(result["components"]), "independent_bottom_verified": 0}))


if __name__ == "__main__":
    main()

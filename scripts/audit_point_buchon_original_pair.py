#!/usr/bin/env python3
"""Audit original Point Buchon bathymetry, character, and open-reference ROV.

Research-only aggregates: no survey coordinates, fishing marks, or exports.
The USGS bathymetry has no established MLLW datum or cell uncertainty.
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

import numpy as np
import rasterio
from rasterio.windows import Window

from scripts.build_central_rov_depth_evidence import fetch as fetch_rov, source_bytes

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BATHY = "c825293fc999ad757b32ee2acefcae590690d451d12fd367b2f8b3e9e6d731d4"
EXPECTED_CLASS = "0a9579783e5318bfee0ebef8ede112f32c5a2202272338ae9eb1fd9e96df8bc1"
EXPECTED_METADATA = "5df595ce78430c89fad4d244337bf8187bd7ccbbee343e85f19082d3d2ec7214"
EXPECTED_BATHY_METADATA = "67f5bd344c133d44fdabc3893f15dc7da6f0c69a30017d62ccfcfed60b4eec63"
LOWER_M, UPPER_M = 200 / 3.280839895, 300 / 3.280839895
CLASS_NAMES = {1: "soft_flat", 2: "hard_flat", 3: "hard_rugose"}


def original_tiff(archive):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != (
        EXPECTED_BATHY if "Bathymetry" in archive.name else EXPECTED_CLASS
    ):
        raise ValueError(f"Original USGS archive hash changed: {archive}")
    with zipfile.ZipFile(archive) as source:
        names = [name for name in source.namelist() if name.lower().endswith(".tif")]
        if len(names) != 1:
            raise ValueError("Expected one original GeoTIFF")
        return f"zip://{archive.resolve()}!{names[0]}"


def verify_semantics(metadata):
    raw = metadata.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_METADATA:
        raise ValueError("USGS character metadata changed")
    text = raw.decode("utf-8")
    for phrase in ("hard and flat coarse grain sediment and bedrock seafloor",
                   "hard and rugose boulder, megaclast, and bedrock seafloor",
                   "There were 304 observations in the study area"):
        if phrase not in text:
            raise ValueError("USGS character meaning or video audit changed")
    return hashlib.sha256(raw).hexdigest()


def verify_bathy_processing(metadata):
    raw = metadata.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_BATHY_METADATA:
        raise ValueError("USGS bathymetry processing metadata changed")
    text = raw.decode("utf-8")
    for phrase in ("a 2-meter resolution image for depths less than 80 meters",
                   "a 5-meter resolution image for deeper areas",
                   "mosaiced into a single 2-meter resolution image",
                   "Estimated to be no less than 20 cm"):
        if phrase not in text:
            raise ValueError("USGS bathymetry resolution or uncertainty description changed")
    if "<vertdef>" in text or "<altdef>" in text:
        raise ValueError("USGS output vertical datum declaration requires review")
    return hashlib.sha256(raw).hexdigest()


def fetch_original(leads, bathy, character, metadata, bathy_metadata):
    area = next(row for row in leads["map_areas"] if row["name"] == "Offshore of Point Buchon")
    products = {row["description"]: row for row in area["products"]}
    sources = [
        (products["Bathymetry_OffshorePointBuchon"]["archive_url"], bathy, EXPECTED_BATHY),
        (products["Bathymetry_OffshorePointBuchon"]["metadata_url"], bathy_metadata, EXPECTED_BATHY_METADATA),
        (products["SeafloorCharacter_OffshorePointBuchon"]["archive_url"], character, EXPECTED_CLASS),
        (products["SeafloorCharacter_OffshorePointBuchon"]["metadata_url"], metadata, EXPECTED_METADATA),
    ]
    for url, path, expected in sources:
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".download")
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SkipperCast source audit; +https://skippercast.com)"})
        with urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            temporary.unlink()
            raise ValueError(f"Official USGS object changed: {url}")
        temporary.replace(path)


def aggregate(bathy_zip, class_zip, class_metadata, bathy_metadata, rov_csv, rov_pin):
    source_bytes(rov_csv, rov_pin)
    metadata_hash = verify_semantics(class_metadata)
    bathy_metadata_hash = verify_bathy_processing(bathy_metadata)
    bathy_path, class_path = original_tiff(bathy_zip), original_tiff(class_zip)
    paired = defaultdict(lambda: {"cells": 0, "area_m2": 0,
                                  "cells_from_under_80m_2m_source": 0,
                                  "cells_from_at_or_over_80m_5m_source": 0})
    sampled = defaultdict(lambda: {"subunits": 0, "camera_area_m2": 0.0,
                                     "lingcod_seen": 0, "vermilion_rockfish_seen": 0,
                                     "observed_depths_m": [],
                                     "depth_differences_m": [], "years": set(),
                                     "ten_m_hard_rugose_shares": [], "ten_m_center_class_majority": 0,
                                     "centers_on_at_or_over_80m_5m_source": 0})
    with rasterio.open(bathy_path) as bathy, rasterio.open(class_path) as character:
        if (bathy.count != 1 or character.count != 1 or
                str(bathy.crs) != "EPSG:32610" or str(character.crs) != "EPSG:32610" or
                bathy.transform != character.transform or bathy.shape != character.shape or
                any(abs(x - 2) > .01 for x in bathy.res + character.res)):
            raise ValueError("Original USGS 2 m grids are not aligned as expected")
        for _, window in bathy.block_windows(1):
            d = bathy.read(1, window=window, masked=True)
            c = character.read(1, window=window, masked=True)
            depth = np.ma.getdata(d)
            kind = np.ma.getdata(c)
            valid = ~np.ma.getmaskarray(d) & ~np.ma.getmaskarray(c) & np.isfinite(depth)
            band = valid & (-depth >= LOWER_M) & (-depth <= UPPER_M)
            for code, label in CLASS_NAMES.items():
                n = int(np.count_nonzero(band & (kind == code)))
                paired[label]["cells"] += n
                paired[label]["area_m2"] += n * 4
                paired[label]["cells_from_under_80m_2m_source"] += int(np.count_nonzero(
                    band & (kind == code) & (-depth < 80)))
                paired[label]["cells_from_at_or_over_80m_5m_source"] += int(np.count_nonzero(
                    band & (kind == code) & (-depth >= 80)))
        with rov_csv.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            required = {"LongTerm_Region", "Protection", "Type", "MPAGroup", "Avg.X", "Avg.Y",
                        "Avg.Depth", "SurveyYear", "X10m_ID", "Usable_Area_Fish", "Lingcod", "Vermilion_rf"}
            if not required.issubset(reader.fieldnames):
                raise ValueError("ROV source schema changed")
            seen = set()
            for row in reader:
                if (row["LongTerm_Region"] != "Central" or row["MPAGroup"] != "Point Buchon"
                        or row["Protection"] != "0" or row["Type"] != "Reference"):
                    continue
                observed_depth = float(row["Avg.Depth"])
                if not LOWER_M <= observed_depth <= UPPER_M:
                    continue
                ident = row["X10m_ID"]
                if ident in seen:
                    raise ValueError("Duplicate ROV subunit")
                seen.add(ident)
                # Analysis release stores UTM zone 10 GRS80 coordinates in kilometres.
                x, y = float(row["Avg.X"]) * 1000, float(row["Avg.Y"]) * 1000
                b = next(bathy.sample([(x, y)], masked=True))[0]
                c = next(character.sample([(x, y)], masked=True))[0]
                if np.ma.is_masked(b) or np.ma.is_masked(c) or int(c) not in CLASS_NAMES:
                    label = "unpaired"
                else:
                    label = CLASS_NAMES[int(c)]
                item = sampled[label]
                item["subunits"] += 1
                item["camera_area_m2"] += float(row["Usable_Area_Fish"])
                item["observed_depths_m"].append(observed_depth)
                item["lingcod_seen"] += int(row["Lingcod"])
                item["vermilion_rockfish_seen"] += int(row["Vermilion_rf"])
                item["years"].add(int(row["SurveyYear"]))
                if label != "unpaired":
                    item["centers_on_at_or_over_80m_5m_source"] += int(-float(b) >= 80)
                    item["depth_differences_m"].append(round(-float(b) - observed_depth, 2))
                    center_row, center_col = character.index(x, y)
                    window = Window(center_col - 5, center_row - 5, 11, 11)
                    neighborhood = character.read(1, window=window, masked=True, boundless=True)
                    transform = character.window_transform(window)
                    rr, cc = np.mgrid[0:11, 0:11]
                    cx = transform.c + (cc + 0.5) * transform.a
                    cy = transform.f + (rr + 0.5) * transform.e
                    within = (cx - x) ** 2 + (cy - y) ** 2 <= 100
                    valid_nearby = within & ~np.ma.getmaskarray(neighborhood)
                    codes_nearby = np.ma.getdata(neighborhood)
                    if np.count_nonzero(valid_nearby):
                        item["ten_m_hard_rugose_shares"].append(
                            float(np.count_nonzero(valid_nearby & (codes_nearby == 3)) /
                                  np.count_nonzero(valid_nearby)))
                        if np.count_nonzero(valid_nearby & (codes_nearby == int(c))) > np.count_nonzero(valid_nearby) / 2:
                            item["ten_m_center_class_majority"] += 1
    rows = []
    for label, item in sorted(sampled.items()):
        differences = item.pop("depth_differences_m")
        observed_depths = item.pop("observed_depths_m")
        nearby_shares = item.pop("ten_m_hard_rugose_shares")
        same_majority = item.pop("ten_m_center_class_majority")
        years = sorted(item.pop("years"))
        rows.append({"center_character_class": label,
                     "subunits": item["subunits"],
                     "camera_area_m2": round(item["camera_area_m2"], 1),
                     "lingcod_seen": item["lingcod_seen"],
                     "vermilion_rockfish_seen": item["vermilion_rockfish_seen"],
                     "observation_years": years,
                     "observed_depth_range_m": [round(min(observed_depths), 2),
                                                round(max(observed_depths), 2)],
                     "centers_on_at_or_over_80m_5m_source": item["centers_on_at_or_over_80m_5m_source"],
                     "median_nominal_depth_difference_m": round(float(np.median(differences)), 2) if differences else None,
                     "mean_hard_rugose_fraction_within_10m": round(float(np.mean(nearby_shares)), 3) if nearby_shares else None,
                     "centers_matching_10m_majority": same_majority})
    return {"schema_version": 1, "scope": "point-buchon-original-paired-200-300ft-research",
            "fishing_target": False, "exportable": False, "qualified_waypoints": 0,
            "source_release": "https://doi.org/10.5066/P9KBGELE",
            "bathy_archive_sha256": EXPECTED_BATHY, "character_archive_sha256": EXPECTED_CLASS,
            "character_metadata_sha256": metadata_hash,
            "bathymetry_metadata_sha256": bathy_metadata_hash,
            "rov_source_doi": rov_pin["doi"], "rov_source_sha256": rov_pin["file_sha256"],
            "published_grid_resolution_m": 2,
            "source_gridding_resolution_m": {"under_80m": 2, "deeper_than_80m": 5,
                                             "80m_boundary": "treated with deeper band for conservative count"},
            "native_depth_datum": "unresolved",
            "nominal_depth_band_ft": [200, 300],
            "paired_nominal_band_by_character": {key: paired[key] for key in CLASS_NAMES.values()},
            "open_reference_rov_at_nominal_centers": rows,
            "limitations": [
                "USGS class 2 is hard/flat; class 3 is hard/rugose boulder, megaclast and bedrock; neither is an individual boulder measurement.",
                "ROV center overlay is nominal; independent survey coordinate accuracy, datum realization, epoch, and 10 m observation support are unresolved.",
                "USGS bathymetry lacks an established MLLW output datum and per-cell upper uncertainty bound; nominal 200–300 ft is not a fishing-depth clearance.",
                "The published 2 m bathymetry mosaic includes 5 m gridded source data deeper than 80 m; its 2 m pixel spacing is not 2 m independent depth detail there.",
                "Historical ROV counts are visual observations, not present fish, angler catch rates, or spot-level validation.",
                "No full-footprint MPA, chart hazard, access, approach/return, or drift screen has qualified these cells for fishing or export.",
            ]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bathy", type=Path, default=ROOT / "var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon.zip")
    p.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip")
    p.add_argument("--character-metadata", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon_metadata.xml")
    p.add_argument("--bathy-metadata", type=Path, default=ROOT / "var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon_metadata.xml")
    p.add_argument("--rov", type=Path, default=ROOT / "var/review/rov-zenodo-10929417.csv")
    p.add_argument("--fetch", action="store_true", help="Fetch pinned original USGS and published ROV objects")
    p.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-original-paired-200-300ft-review.json")
    args = p.parse_args()
    pin = json.loads((ROOT / "catalog/central-rov-2024-source.json").read_text())
    if args.fetch:
        leads = json.loads((ROOT / "dist/data/usgs-ds781-source-leads.json").read_text())
        fetch_original(leads, args.bathy, args.character, args.character_metadata, args.bathy_metadata)
        fetch_rov(pin, args.rov)
    report = aggregate(args.bathy, args.character, args.character_metadata,
                       args.bathy_metadata, args.rov, pin)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{sum(x['cells'] for x in report['paired_nominal_band_by_character'].values())} nominal paired cells; zero fishing waypoints")


if __name__ == "__main__":
    main()

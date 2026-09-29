"""Probe official GEOID03 NAVD88-to-MLLW offsets over private Point Buchon blocks.

This samples NOAA's model, not a validated conversion of the 2009 grid. Source
horizontal realization/epoch and source total depth uncertainty remain unknown.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from pyproj import Transformer
from shapely.geometry import shape

from research.lib.paths import ROOT

from research.scripts.audit_point_buchon_2009_csumb_products import sha256_file


ARCHIVE_URL = "https://vdatum.noaa.gov/download/data/CAmorrob01_8301.zip"
ARCHIVE_SHA256 = "64f586db40ba0776ca38d7bce6762e2138594f31f8d96fe6f8e3b4f7b7b53984"
ARCHIVE_BYTES = 14965488
META_MEMBER = "vdatum/CAmorrob01_8301/CAmorrob01_8301.met"
API = "https://vdatum.noaa.gov/vdatumweb/api/convert"
SAMPLE_COUNT = 12


def regional_metadata(archive):
    if archive.stat().st_size != ARCHIVE_BYTES or sha256_file(archive) != ARCHIVE_SHA256:
        raise ValueError("Official VDatum Morro Bay archive changed")
    with ZipFile(archive) as package:
        source = package.read(META_MEMBER).decode("utf-8")
    meta = dict(line.split("=", 1) for line in source.splitlines() if "=" in line)
    if (meta.get("description") != "CAmorrob01_8301"
            or meta.get("horz") != "NAD83"
            or meta.get("tidal_epoch") != "1983-2001"
            or meta.get("tidal.released_date") != "06/20/2019"):
        raise ValueError("Official VDatum region metadata changed")
    return meta


def sample_centers(blocks):
    if (blocks.get("scope") != "private-point-buchon-2009-csumb-100m-research-blocks"
            or len(blocks.get("features", [])) != 181
            or blocks.get("crs") != "EPSG:32610"):
        raise ValueError("Private research-block identity or CRS changed")
    centers = sorted((shape(feature["geometry"]).representative_point().x,
                      shape(feature["geometry"]).representative_point().y)
                     for feature in blocks["features"])
    selected = [centers[0]]
    while len(selected) < SAMPLE_COUNT:
        remaining = [point for point in centers if point not in selected]
        selected.append(max(remaining, key=lambda point: (
            min((point[0] - old[0]) ** 2 + (point[1] - old[1]) ** 2 for old in selected),
            -point[0], -point[1])))
    return sorted(selected)


def probe(lon, lat, frame="NAD83_2011"):
    params = {"region": "westcoast", "s_x": f"{lon:.8f}", "s_y": f"{lat:.8f}",
              "s_z": "0", "s_h_frame": frame, "s_coor": "geo",
              "s_v_frame": "NAVD88", "s_v_geoid": "geoid03",
              "s_v_unit": "m", "s_v_elevation": "height",
              "t_h_frame": "IGS14", "t_coor": "geo", "t_v_frame": "MLLW",
              "t_v_unit": "m", "t_v_elevation": "height"}
    url = API + "?" + urlencode(params)
    with urlopen(Request(url, headers={"Accept": "application/json",
                                       "User-Agent": "SkipperCast bounded datum-source review/1.0"}),
                 timeout=30) as response:
        if response.status != 200 or response.url != url or "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Official VDatum response status or content changed")
        raw = response.read(10001)
    if not raw or len(raw) > 10000:
        raise ValueError("Official VDatum response size changed")
    payload = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if frame == "NAD83_1986":
        if payload.get("errorCode") != 412 or "should be NAD83_2011" not in payload.get("message", ""):
            raise ValueError("VDatum alternate-frame behavior changed")
        return {"status": "rejected", "error_code": 412, "response_sha256": digest}
    expected = {"region": "WESTCOAST", "s_h_frame": frame,
                "s_v_frame": "NAVD88", "s_v_geoid": "geoid03",
                "s_v_unit": "m", "t_h_frame": "IGS14",
                "t_v_frame": "MLLW", "t_v_unit": "m"}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("VDatum input/output frame echo changed")
    values = {key: float(payload[key]) for key in ("s_x", "s_y", "s_z", "t_x", "t_y", "t_z", "uncertainty")}
    if (not all(math.isfinite(value) for value in values.values())
            or abs(values["s_x"] - lon) > 1e-6 or abs(values["s_y"] - lat) > 1e-6
            or values["s_z"] != 0 or abs(values["t_x"] - lon) > .01
            or abs(values["t_y"] - lat) > .01
            or not -20 < values["t_z"] < 20
            or not 0 < values["uncertainty"] < 20):
        raise ValueError("VDatum sentinel, coordinate or uncertainty changed")
    return {"status": "available", "offset_m": values["t_z"],
            "vdatum_uncertainty_m": values["uncertainty"], "response_sha256": digest}


def audit(archive, block_path):
    meta = regional_metadata(archive)
    blocks = json.loads(block_path.read_text())
    selected = sample_centers(blocks)
    transform = Transformer.from_crs(32610, 4326, always_xy=True)
    samples = []
    for x, y in selected:
        lon, lat = transform.transform(x, y)
        if not (float(meta["minlon"]) < lon % 360 < float(meta["maxlon"])
                and float(meta["minlat"]) < lat < float(meta["maxlat"])):
            raise ValueError("Research block outside official VDatum region extent")
        samples.append(probe(lon, lat))
    lon, lat = transform.transform(*selected[0])
    alternative = probe(lon, lat, "NAD83_1986")
    offsets = [row["offset_m"] for row in samples]
    uncertainty = [row["vdatum_uncertainty_m"] for row in samples]
    return {
        "schema_version": 1,
        "scope": "point-buchon-2009-csumb-conditional-geoid03-vdatum-model-probes",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "official_api": API, "official_regional_archive_url": ARCHIVE_URL,
        "official_regional_archive_sha256": ARCHIVE_SHA256,
        "regional_grid_tidal_epoch": meta["tidal_epoch"],
        "regional_grid_tidal_release_date": meta["tidal.released_date"],
        "delivered_product_metadata_year": 2009,
        "bundled_bathymetry_trackline_year": 2007,
        "cell_acquisition_year_verified": False,
        "private_block_count": len(blocks["features"]),
        "sample_count": len(samples),
        "conditional_navd88_zero_to_mllw_offset_m": [min(offsets), max(offsets)],
        "api_reported_transformation_uncertainty_m": [min(uncertainty), max(uncertainty)],
        "sample_response_sha256": [row["response_sha256"] for row in samples],
        "alternate_nad83_1986_probe": alternative,
        "source_horizontal_realization_and_epoch_verified": False,
        "full_source_cell_conversion": False,
        "source_product_upper_uncertainty_verified": False,
        "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
        "limitations": [
            "The Block A3 delivered raster declares NAD83 UTM10 and NAVD88 Geoid03, but not the NAD83 realization or coordinate epoch. Its bundled bathymetry tracklines date to 2007 despite metadata mentioning 2009 block surveys. The accepted NAD83_2011 API path is conditional on an unverified source-frame identity.",
            "Twelve actual private research-block centers sample a NOAA model field; they do not convert every measured depth cell or prove interpolation error over all blocks.",
            "VDatum uncertainty describes the transformation, not the original CSUMB bathymetry total propagated uncertainty. The source metadata leave vertical accuracy empty.",
            "No original-depth cell, rock substrate, fish presence, legal route or fishing date is qualified by this probe.",
        ],
    }


def stable(result):
    return {key: value for key, value in result.items() if key != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "var/review/vdatum-point-buchon/CAmorrob01_8301.zip")
    parser.add_argument("--blocks", type=Path, default=ROOT / "var/review/point-buchon-2009-csumb-100m-blocks.geojson")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-2009-conditional-vdatum-probes.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch and not args.archive.exists():
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(Request(ARCHIVE_URL, headers={"User-Agent": "SkipperCast original VDatum archive audit/1.0"}), timeout=90) as source:
            data = source.read(ARCHIVE_BYTES + 1)
        if len(data) != ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Official VDatum regional archive bytes changed")
        args.archive.write_bytes(data)
    result = audit(args.archive, args.blocks)
    if args.verify and stable(result) != stable(json.loads(args.verify.read_text())):
        raise ValueError("Point Buchon VDatum field or source identity changed; review before publication")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print({"samples": result["sample_count"],
           "conditional_offset_range_m": result["conditional_navd88_zero_to_mllw_offset_m"],
           "qualified_waypoints": 0})


if __name__ == "__main__":
    main()

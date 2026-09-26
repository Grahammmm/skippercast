#!/usr/bin/env python3
"""Probe NOAA VDatum at Monterey research outlines without converting source pixels.

The USGS source says NAD83 but omits its realization/epoch. NOAA's West Coast
web route requires NAD83(2011), so these are conditional model probes only.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile

from shapely.geometry import shape


BASE = "https://vdatum.noaa.gov/vdatumweb/api/convert"
ARCHIVE_URL = "https://www.vdatum.noaa.gov/download/data/CAmontby13_8301.zip"
ARCHIVE_SHA256 = "6c1b3c900563500eb9bafb4f04e5a6deabfbdfa26e66b53f2c1510b7f3778b62"
META_NAME = "CAmontby13_8301/CAmontby13_8301.met"


def archive_metadata(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError("NOAA regional-grid archive bytes changed; review before use")
    with zipfile.ZipFile(path) as zipped:
        lines = zipped.read(META_NAME).decode("utf-8").splitlines()
    meta = dict(line.split("=", 1) for line in lines if "=" in line)
    if (meta.get("horz") != "IGS14" or meta.get("tidal_epoch") != "1983-2001"
            or meta.get("tidal.released_date") != "03/26/2024"):
        raise ValueError("NOAA regional-grid metadata changed")
    return digest, meta


def request_url(lon, lat):
    if not (-122.2 < lon < -121.6 and 36.5 < lat < 36.85):
        raise ValueError("Probe outside bounded Monterey review area")
    params = {"region": "westcoast", "s_x": f"{lon:.8f}", "s_y": f"{lat:.8f}",
              "s_z": "0", "s_h_frame": "NAD83_2011", "s_coor": "geo",
              "s_v_frame": "NAVD88", "s_v_unit": "m", "s_v_elevation": "height",
              "t_h_frame": "IGS14", "t_coor": "geo", "t_v_frame": "MLLW",
              "t_v_unit": "m", "t_v_elevation": "height"}
    return BASE + "?" + urlencode(params)


def fetch(url):
    if not url.startswith(BASE + "?region=westcoast&"):
        raise ValueError("Unreviewed VDatum request")
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast research-only VDatum probe"}), timeout=35) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("VDatum status or redirect changed")
        raw = response.read(10_001)
    if not raw or len(raw) > 10_000:
        raise ValueError("Empty or oversized VDatum response")
    return raw


def parse(raw, lon, lat):
    item = json.loads(raw)
    if (item.get("region") != "WESTCOAST" or item.get("s_h_frame") != "NAD83_2011"
            or item.get("t_h_frame") != "IGS14" or item.get("s_v_frame") != "NAVD88"
            or item.get("t_v_frame") != "MLLW" or item.get("s_v_unit") != "m"
            or item.get("t_v_unit") != "m" or item.get("s_v_elevation") != "height"
            or item.get("t_v_elevation") != "height"
            or item.get("epoch_in") != "0.0" or item.get("epoch_out") != "0.0"):
        raise ValueError("VDatum model route or response semantics changed")
    values = {key: float(item[key]) for key in ("s_x", "s_y", "s_z", "t_x", "t_y", "t_z", "uncertainty")}
    if (not all(math.isfinite(value) for value in values.values())
            or abs(values["s_x"] - lon) > 0.000001
            or abs(values["s_y"] - lat) > 0.000001
            or values["s_z"] != 0 or not 0 < values["uncertainty"] < 5
            or not -10 < values["t_z"] < 10
            or abs(values["t_x"] - lon) > 0.001
            or abs(values["t_y"] - lat) > 0.001):
        raise ValueError("VDatum result or uncertainty invalid")
    return {"conditional_navd88_zero_to_mllw_m": round(values["t_z"], 3),
            "vdatum_reported_uncertainty_m": round(values["uncertainty"], 3),
            "target_lon_igs14": values["t_x"], "target_lat_igs14": values["t_y"]}


def probe(feature):
    point = shape(feature["geometry"]).representative_point()
    lon, lat = point.x, point.y
    url = request_url(lon, lat)
    raw = fetch(url)
    return {"context_id": feature["properties"]["id"],
            "source_lon_assumed_nad83_2011": round(lon, 8),
            "source_lat_assumed_nad83_2011": round(lat, 8),
            "request_url": url, "response_sha256": hashlib.sha256(raw).hexdigest(),
            **parse(raw, lon, lat), "fishing_target": False, "exportable": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, default=Path("dist/data/usgs-offshore-monterey-hard-context.geojson"))
    parser.add_argument("--pixel", type=Path, default=Path("dist/data/monterey-original-300-pixel-review.json"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive_sha, meta = archive_metadata(args.archive)
    context = json.loads(args.context.read_text())
    pixel = json.loads(args.pixel.read_text())
    if pixel.get("scope") != "monterey-original-pixel-depth-band-audit" or pixel.get("fishing_target") is not False:
        raise ValueError("Wrong research depth-band receipt")
    by_id = {feature["properties"]["id"]: feature for feature in context["features"]}
    features = [by_id[row["context_id"]] for row in pixel["outlines"]]
    if len(features) != pixel["outline_count"] or any(f["properties"].get("fishing_target") is not False for f in features):
        raise ValueError("Research outlines changed")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(probe, features))
    report = {"schema_version": 1, "scope": "monterey-300-conditional-vdatum-model-probes",
              "probed_at": datetime.now(timezone.utc).isoformat(), "official_api": BASE,
              "official_regional_archive_url": ARCHIVE_URL, "official_regional_archive_sha256": archive_sha,
              "regional_grid_horizontal_frame": meta["horz"], "regional_grid_tidal_epoch": meta["tidal_epoch"],
              "regional_grid_tidal_release_date": meta["tidal.released_date"],
              "source_horizontal_assumption": "NAD83_2011; unverified against source USGS NAD83 realization/epoch",
              "api_horizontal_epoch_in_out": "0.0/0.0 defaults; no documented source acquisition epoch applied",
              "source_vertical_frame": "NAVD88", "target_horizontal_frame": "IGS14",
              "target_vertical_frame": "MLLW", "outline_count": len(rows), "probes": rows,
              "fishing_target": False, "exportable": False,
              "limitations": "One interior point per generalized research outline. API responses do not give a full-patch transform, guarantee interpolation coverage, identify the USGS horizontal realization/epoch, or include USGS source measurement uncertainty. API-reported uncertainty is not the total survey-depth bound. No original depth cell is converted or qualified here."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{len(rows)} conditional official VDatum probes; zero qualified fishing targets")


if __name__ == "__main__":
    main()

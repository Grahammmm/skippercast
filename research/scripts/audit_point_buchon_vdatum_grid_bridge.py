#!/usr/bin/env python3
"""Compare local VDatum GTX shortcuts with the official conversion API.

This diagnoses, but does not resolve, the CSUMB Geoid03/NAD83 frame bridge.
No source bathymetry is transformed or promoted by this audit.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from pyproj import Transformer
import rasterio

from research.scripts.audit_point_buchon_2009_vdatum_probe import (
    API, ROOT, sample_centers, probe, regional_metadata, ARCHIVE_SHA256,
)


def lmsl_probe(lon, lat):
    params = {"region": "westcoast", "s_x": f"{lon:.8f}", "s_y": f"{lat:.8f}",
              "s_z": "0", "s_h_frame": "NAD83_2011", "s_coor": "geo",
              "s_v_frame": "NAVD88", "s_v_geoid": "geoid03",
              "s_v_unit": "m", "s_v_elevation": "height", "t_h_frame": "IGS14",
              "t_coor": "geo", "t_v_frame": "LMSL", "t_v_unit": "m",
              "t_v_elevation": "height"}
    url = API + "?" + urlencode(params)
    with urlopen(Request(url, headers={"Accept": "application/json",
                                       "User-Agent": "SkipperCast VDatum grid-bridge research/1.0"}),
                 timeout=30) as response:
        if response.status != 200 or response.url != url or "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Official VDatum LMSL response changed")
        raw = response.read(10001)
    if not raw or len(raw) > 10000:
        raise ValueError("Official VDatum LMSL response size changed")
    data = json.loads(raw)
    expected = {"region": "WESTCOAST", "s_h_frame": "NAD83_2011",
                "s_v_frame": "NAVD88", "s_v_geoid": "geoid03",
                "t_h_frame": "IGS14", "t_v_frame": "LMSL"}
    if any(data.get(k) != v for k, v in expected.items()):
        raise ValueError("Official VDatum LMSL datum path changed")
    if abs(float(data["s_x"]) - lon) > 1e-6 or abs(float(data["s_y"]) - lat) > 1e-6:
        raise ValueError("Official VDatum LMSL coordinates changed")
    return float(data["t_z"]), hashlib.sha256(raw).hexdigest()


def summarize(rows):
    if not rows:
        raise ValueError("No VDatum grid/API comparison rows")
    keys = ("api_navd88_to_mllw", "api_navd88_to_lmsl", "api_lmsl_to_mllw_step",
            "raw_grid_mllw_minus_tss", "api_minus_raw_grid_shortcut",
            "raw_grid_negative_mllw", "api_tidal_step_minus_raw_grid_negative_mllw")
    return {key + "_range_m": [round(min(r[key] for r in rows), 5),
                                 round(max(r[key] for r in rows), 5)] for key in keys}


def audit(root):
    archive = root / "var/review/vdatum-point-buchon/CAmorrob01_8301.zip"
    regional_metadata(archive)  # validates official archive bytes and epoch
    blocks_path = root / "var/review/point-buchon-2009-csumb-100m-blocks.geojson"
    centers = sample_centers(json.loads(blocks_path.read_text()))
    grid_root = root / "var/review/vdatum-point-buchon/vdatum/CAmorrob01_8301"
    tss_path, mllw_path = grid_root / "tss.gtx", grid_root / "mllw.gtx"
    with ZipFile(archive) as package:
        for name, path in (("tss.gtx", tss_path), ("mllw.gtx", mllw_path)):
            member = f"vdatum/CAmorrob01_8301/{name}"
            if hashlib.sha256(package.read(member)).digest() != hashlib.sha256(path.read_bytes()).digest():
                raise ValueError("Local GTX bytes differ from the pinned official archive")
    convert = Transformer.from_crs(32610, 4326, always_xy=True)
    rows, response_hashes = [], []
    with rasterio.open(tss_path) as tss, rasterio.open(mllw_path) as mllw:
        if (tss.driver != "GTX" or mllw.driver != "GTX" or tss.crs != mllw.crs
                or tss.transform != mllw.transform or tss.crs.to_epsg() != 4326):
            raise ValueError("Unexpected official GTX grid geometry")
        for x, y in centers:
            lon, lat = convert.transform(x, y)
            grid_x = lon % 360
            tss_value = float(next(tss.sample([(grid_x, lat)]))[0])
            mllw_value = float(next(mllw.sample([(grid_x, lat)]))[0])
            if (tss_value == tss.nodata or mllw_value == mllw.nodata
                    or not -2 < tss_value < 2 or not -2 < mllw_value < 2):
                raise ValueError("VDatum GTX sample is nodata or outside expected range")
            api_mllw = probe(lon, lat)
            api_lmsl, lmsl_hash = lmsl_probe(lon, lat)
            response_hashes.extend((api_mllw["response_sha256"], lmsl_hash))
            tidal_step = api_mllw["offset_m"] - api_lmsl
            raw_shortcut = mllw_value - tss_value
            rows.append({"api_navd88_to_mllw": api_mllw["offset_m"],
                         "api_navd88_to_lmsl": api_lmsl,
                         "api_lmsl_to_mllw_step": tidal_step,
                         "raw_grid_mllw_minus_tss": raw_shortcut,
                         "api_minus_raw_grid_shortcut": api_mllw["offset_m"] - raw_shortcut,
                         "raw_grid_negative_mllw": -mllw_value,
                         "api_tidal_step_minus_raw_grid_negative_mllw": tidal_step + mllw_value})
    result = {"schema_version": 1,
              "scope": "point-buchon-geoid03-vdatum-raw-grid-vs-api-diagnostic",
              "official_api": API,
              "official_regional_archive_sha256": ARCHIVE_SHA256,
              "private_block_count": 181, "sample_count": len(rows),
              "sampling": "12 spatially spread 100 m private-block representative points; nearest GTX pixel; API source NAD83(2011)/NAVD88 Geoid03, target IGS14/LMSL or MLLW",
              "source_sha256": {"private_blocks": hashlib.sha256(blocks_path.read_bytes()).hexdigest(),
                                "tss_gtx": hashlib.sha256(tss_path.read_bytes()).hexdigest(),
                                "mllw_gtx": hashlib.sha256(mllw_path.read_bytes()).hexdigest()},
              "api_response_sha256": response_hashes,
              "source_horizontal_realization_verified": False,
              "full_cellwise_depth_conversion": False,
              "source_depth_upper_uncertainty_verified": False,
              "fishing_target": False, "exportable": False,
              "limitations": "A raw GTX subtraction does not reproduce the official multi-frame VDatum API path; its residual is diagnostic, not an uncertainty bound or a fitted correction. The source horizontal realization/epoch and raster vertical accuracy remain unknown. Twelve nearest-pixel samples do not certify all 2 m/5 m source cells, substrate, fish, legal access or routes."}
    result.update(summarize(rows))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("research/receipts/point-buchon-vdatum-grid-api-bridge.json"))
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if result != {key: value for key, value in saved.items() if key != "checked_at"}:
            raise ValueError("Official VDatum grid/API diagnostic changed; review source or method")
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("12 official VDatum grid/API path comparisons; zero converted fishing cells")


if __name__ == "__main__":
    main()

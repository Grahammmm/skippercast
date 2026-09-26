#!/usr/bin/env python3
"""Sample NOAA's NAVD88-to-MLLW offset across Estero research blocks.

This diagnoses geographic variation only. The source survey is NAD83(CORS96)
at epoch 2010.1548, while the current API accepts NAD83(2011) for NAVD88;
the bridge, source total uncertainty, and cellwise conversion remain open.
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

from pyproj import Transformer


API = "https://vdatum.noaa.gov/vdatumweb/api/convert"
DOC = "https://vdatum.noaa.gov/docs/services.html"


def extent(blocks):
    if blocks.get("type") != "FeatureCollection" or len(blocks.get("features", [])) != 60:
        raise ValueError("Expected 60 private Estero research blocks")
    points = []

    def visit(value):
        if (isinstance(value, list) and len(value) == 2
                and all(isinstance(x, (float, int)) and math.isfinite(x) for x in value)):
            points.append(value)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for feature in blocks["features"]:
        if feature.get("properties", {}).get("fishing_target") is not False:
            raise ValueError("Research geometry unexpectedly became a fishing target")
        visit(feature["geometry"]["coordinates"])
    if not points:
        raise ValueError("No research block geometry")
    x, y = zip(*points)
    result = [min(x), min(y), max(x), max(y)]
    if (not 2000 <= result[2] - result[0] <= 10000
            or not 1000 <= result[3] - result[1] <= 8000):
        raise ValueError("Private research block envelope changed")
    return result


def sample(x, y, to_geo):
    lon, lat = to_geo.transform(x, y)
    params = {"region": "westcoast", "s_x": f"{lon:.8f}", "s_y": f"{lat:.8f}",
              "s_z": "0", "s_h_frame": "NAD83_2011", "s_v_frame": "NAVD88",
              "s_v_unit": "m", "t_h_frame": "IGS14", "t_v_frame": "MLLW", "t_v_unit": "m"}
    url = API + "?" + urlencode(params)
    with urlopen(Request(url, headers={"Accept": "application/json",
                                       "User-Agent": "SkipperCast spatial datum source audit/1.0"}),
                 timeout=25) as response:
        if response.status != 200 or "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("VDatum did not return HTTP 200 JSON")
        data = json.load(response)
    if (data.get("errorCode") or data.get("s_h_frame") != "NAD83_2011"
            or data.get("s_v_frame") != "NAVD88" or data.get("t_v_frame") != "MLLW"
            or data.get("region") != "WESTCOAST"):
        raise ValueError("VDatum conversion failed or returned a different frame")
    offset, uncertainty = float(data["t_z"]), float(data["uncertainty"])
    if not math.isfinite(offset) or not math.isfinite(uncertainty) or not -20 < offset < 20 or not 0 < uncertainty < 20:
        raise ValueError("VDatum returned missing or sentinel values")
    return {"easting_m": round(x, 3), "northing_m": round(y, 3),
            "longitude": round(lon, 8), "latitude": round(lat, 8),
            "offset_m": round(offset, 4), "vdatum_uncertainty_m": round(uncertainty, 4),
            "request_url": url}


def summarize(blocks, samples, nx=7, ny=4):
    bounds = extent(blocks)
    if len(samples) != nx * ny:
        raise ValueError("Incomplete VDatum spatial lattice")
    offsets = [s["offset_m"] for s in samples]
    errors = [s["vdatum_uncertainty_m"] for s in samples]
    adjacent = []
    for row in range(ny):
        for col in range(nx):
            i = row * nx + col
            if col + 1 < nx:
                adjacent.append(abs(offsets[i] - offsets[i + 1]))
            if row + 1 < ny:
                adjacent.append(abs(offsets[i] - offsets[i + nx]))
    if not adjacent:
        raise ValueError("No spatial adjacency")
    return {
        "schema_version": 1, "scope": "estero-2012-vdatum-spatial-offset-diagnostic",
        "service_documentation": DOC,
        "source_survey": "https://doi.org/10.3133/ofr20131225",
        "survey_horizontal_frame": "NAD83(CORS96), processing epoch 2010.1548",
        "api_request_horizontal_frame": "NAD83_2011",
        "source_vertical_datum": "NAVD88 Geoid12",
        "target_vertical_datum": "MLLW",
        "sample_lattice": {"columns": nx, "rows": ny, "points": len(samples),
                           "maximum_spacing_m": round(max((bounds[2] - bounds[0]) / (nx - 1),
                                                      (bounds[3] - bounds[1]) / (ny - 1)), 1)},
        "research_envelope_dimensions_m": [round(bounds[2] - bounds[0]), round(bounds[3] - bounds[1])],
        "offset_m": {"minimum": min(offsets), "maximum": max(offsets),
                     "range": round(max(offsets) - min(offsets), 4),
                     "maximum_adjacent_sample_change": round(max(adjacent), 4)},
        "vdatum_reported_uncertainty_m": {"minimum": min(errors), "maximum": max(errors)},
        "private_sample_receipt_sha256": hashlib.sha256(json.dumps(samples, sort_keys=True).encode()).hexdigest(),
        "converted_source_raster": False, "full_error_budget_resolved": False,
        "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
        "limitations": "These are NOAA point-service samples of a spatial NAVD88-to-MLLW offset, not a converted 2012 raster or a cellwise uncertainty bound. The source CORS96-to-API NAD83(2011) epoch bridge, 2012 CARIS TPU, horizontal registration and interpolation error remain unresolved. No site or route is cleared for fishing."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=Path, default=Path("var/review/estero-nominal-research-blocks.geojson"))
    parser.add_argument("--private-output", type=Path, default=Path("var/review/estero-vdatum-spatial-samples.json"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/estero-2012-vdatum-spatial-diagnostic.json"))
    args = parser.parse_args()
    blocks = json.loads(args.blocks.read_text())
    west, south, east, north = extent(blocks)
    nx, ny = 7, 4
    coordinates = [(west + (east - west) * col / (nx - 1),
                    south + (north - south) * row / (ny - 1))
                   for row in range(ny) for col in range(nx)]
    to_geo = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        samples = list(pool.map(lambda p: sample(p[0], p[1], to_geo), coordinates))
    report = summarize(blocks, samples, nx, ny)
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    args.private_output.write_text(json.dumps({"retrieved_at": datetime.now(timezone.utc).isoformat(),
                                              "source_blocks_sha256": hashlib.sha256(args.blocks.read_bytes()).hexdigest(),
                                              "samples": samples}, indent=2) + "\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["offset_m"], report["vdatum_reported_uncertainty_m"])


if __name__ == "__main__":
    main()

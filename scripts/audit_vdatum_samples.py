"""Check NOAA VDatum coverage at reviewed habitat-context samples.

This is a source-availability audit, not a raster conversion or a depth gate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import shape


API = "https://vdatum.noaa.gov/vdatumweb/api/convert"
NO_RESULT = -999999


def assess_response(payload: dict, longitude: float, latitude: float) -> dict:
    """Reject a syntactically successful response with missing tidal coverage."""
    expected = {
        "region": "WESTCOAST",
        "s_h_frame": "NAD83_2011",
        "s_v_frame": "NAVD88",
        "s_v_unit": "m",
        "t_h_frame": "IGS14",
        "t_v_frame": "MLLW",
        "t_v_unit": "m",
    }
    if not isinstance(payload, dict) or any(payload.get(k) != v for k, v in expected.items()):
        return {"status": "invalid_response", "reason": "frame_or_schema_mismatch"}
    if payload.get("errorCode") is not None:
        return {"status": "invalid_response", "reason": "api_error"}
    try:
        sx, sy = float(payload["s_x"]), float(payload["s_y"])
        offset, uncertainty = float(payload["t_z"]), float(payload["uncertainty"])
        tx, ty = float(payload["t_x"]), float(payload["t_y"])
    except (TypeError, ValueError, KeyError):
        return {"status": "unavailable", "reason": "missing_numeric_result"}
    if abs(sx - longitude) > 1e-5 or abs(sy - latitude) > 1e-5:
        return {"status": "invalid_response", "reason": "source_coordinate_mismatch"}
    if not all(map(math.isfinite, (offset, uncertainty, tx, ty))):
        return {"status": "unavailable", "reason": "nonfinite_result"}
    if offset <= -1e5 or abs(offset) > 20 or uncertainty <= 0 or uncertainty > 20:
        return {"status": "unavailable", "reason": "sentinel_or_invalid_uncertainty"}
    if abs(tx - longitude) > 0.01 or abs(ty - latitude) > 0.01:
        return {"status": "invalid_response", "reason": "target_coordinate_mismatch"}
    return {"status": "sample_available", "offset_m": offset, "vdatum_uncertainty_m": uncertainty}


def fetch_sample(longitude: float, latitude: float) -> tuple[str, dict]:
    params = {
        "region": "westcoast", "s_x": f"{longitude:.7f}", "s_y": f"{latitude:.7f}",
        "s_z": "0", "s_h_frame": "NAD83_2011", "s_v_frame": "NAVD88",
        "s_v_unit": "m", "t_h_frame": "IGS14", "t_v_frame": "MLLW", "t_v_unit": "m",
    }
    url = API + "?" + urlencode(params)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "SkipperCast source-audit/1.0"})
    with urlopen(request, timeout=20) as response:
        if response.status != 200 or "json" not in response.headers.get("Content-Type", "").lower():
            raise RuntimeError("VDatum did not return an HTTP 200 JSON response")
        payload = json.load(response)
    return url, assess_response(payload, longitude, latitude)


def audit(context: dict, depth: dict, coverage_probes: list[tuple[float, float]] | None = None) -> dict:
    if context.get("scope") != "generalized-statewide-usgs-hard-bottom-context":
        raise ValueError("Expected reviewed USGS context polygons")
    if (depth.get("scope") != "original-usgs-bathymetry-vs-habitat-context"
            or depth.get("vertical_datum") != "NAVD88"
            or depth.get("source_id") != "offshore-monterey-character-2016"):
        raise ValueError("Expected original NAVD88 bathymetry review")
    indexed = {feature["properties"]["id"]: feature for feature in context["features"]}
    selected = [row for row in depth["outlines"] if row["historical_camera_interior_windows"] > 0]
    if not selected or any(row["context_id"] not in indexed for row in selected):
        raise ValueError("Missing camera-supported original context geometry")
    samples = []
    for row in selected:
        point = shape(indexed[row["context_id"]]["geometry"]).representative_point()
        lon, lat = round(point.x, 7), round(point.y, 7)
        try:
            url, result = fetch_sample(lon, lat)
        except Exception as exc:
            url = None
            result = {"status": "access_failed", "reason": type(exc).__name__}
        samples.append({"context_id": row["context_id"], "longitude": lon, "latitude": lat,
                        "request_url": url, **result})
    for longitude, latitude in coverage_probes or []:
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError("Invalid coverage-probe coordinates")
        try:
            url, result = fetch_sample(longitude, latitude)
        except Exception as exc:
            url = None
            result = {"status": "access_failed", "reason": type(exc).__name__}
        samples.append({"sample_type": "coverage_probe", "longitude": longitude, "latitude": latitude,
                        "request_url": url, **result})
    return {
        "schema_version": 1, "scope": "noaa-vdatum-point-coverage-audit",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_context": "USGS Offshore Monterey 2 m historical class and NAVD88 bathymetry",
        "source_context_compiled_at": context.get("compiled_at"),
        "source_depth_audited_at": depth.get("audited_at"),
        "service_documentation_url": "https://vdatum.noaa.gov/docs/services.html",
        "source_horizontal_assumption": "NAD83_2011 requested; original EPSG:26910 only identifies NAD83 and does not prove realization or epoch",
        "interpretation": "Zero-height point conversions test service coverage only. An available point does not convert a polygon or original pixels; no source-grid uncertainty, interpolation field, epoch, route, legal or fish review is supplied.",
        "mllw_raster_converted": False, "fishing_target": False, "exportable": False,
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, default=Path("dist/data/usgs-offshore-monterey-hard-context.geojson"))
    parser.add_argument("--depth-review", type=Path, default=Path("dist/data/usgs-offshore-monterey-bathy-context-review.json"))
    parser.add_argument("--probe", action="append", default=[], help="Additional longitude,latitude coverage probe; repeatable")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(Path("dist").resolve()):
        raise ValueError("Write to var/ for human review before publication")
    probes = [tuple(map(float, item.split(","))) for item in args.probe]
    if any(len(item) != 2 for item in probes):
        raise ValueError("--probe must be longitude,latitude")
    result = audit(json.loads(args.context.read_text()), json.loads(args.depth_review.read_text()), probes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"samples": len(result["samples"]), "statuses": [row["status"] for row in result["samples"]]}))
    if any(row["status"] == "access_failed" for row in result["samples"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()

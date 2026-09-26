#!/usr/bin/env python3
"""Check NOAA VDatum frame acceptance near Estero Bay; never convert a grid here."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API = "https://vdatum.noaa.gov/vdatumweb/api/convert"
FRAMES = ("NAD83_CORS96", "NAD83_2011", "NAD83_NSRS2007", "WGS84_G1150")
LON, LAT = -121.03, 35.44  # Regional service probe, not a fishing target.


def classify(frame, result):
    if not isinstance(result, dict):
        raise ValueError("VDatum returned an invalid response")
    if "errorCode" in result:
        return {"status": "rejected", "error_code": result["errorCode"],
                "message": result.get("message")}
    if (result.get("s_h_frame") != frame or result.get("s_v_frame") != "NAVD88"
            or result.get("t_v_frame") != "MLLW" or result.get("region") != "WESTCOAST"):
        raise ValueError("VDatum response frame or region mismatch")
    try:
        offset = float(result["t_z"])
        uncertainty = float(result["uncertainty"])
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("VDatum result lacks offset or uncertainty") from error
    if not -20 < offset < 20 or not 0 < uncertainty < 20:
        raise ValueError("VDatum sentinel or implausible result")
    return {"status": "point_available", "offset_m": offset,
            "vdatum_uncertainty_m": uncertainty}


def audit():
    samples = []
    for frame in FRAMES:
        params = {"region": "westcoast", "s_x": str(LON), "s_y": str(LAT), "s_z": "0",
                  "s_h_frame": frame, "s_v_frame": "NAVD88", "s_v_unit": "m",
                  "t_h_frame": "IGS14", "t_v_frame": "MLLW", "t_v_unit": "m"}
        url = API + "?" + urlencode(params)
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "SkipperCast source-audit/1.0"})
        with urlopen(req, timeout=25) as response:
            if response.status != 200 or "json" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("VDatum did not return HTTP 200 JSON")
            payload = json.load(response)
        samples.append({"requested_horizontal_frame": frame, "request_url": url,
                        **classify(frame, payload)})
    return {"schema_version": 1, "scope": "estero-2012-vdatum-horizontal-frame-availability",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "service_documentation": "https://vdatum.noaa.gov/docs/services.html",
            "source_survey": "https://doi.org/10.3133/ofr20131225",
            "source_survey_horizontal_frame": "NAD83(CORS96), processing epoch 2010.1548",
            "source_survey_vertical_frame": "NAVD88 Geoid12",
            "sample_type": "regional_coverage_only", "sample_longitude": LON, "sample_latitude": LAT,
            "mllw_raster_converted": False, "fishing_target": False, "exportable": False,
            "samples": samples,
            "interpretation": "API point availability does not transform original CORS96 source coordinates, provide a full MLLW surface, or supply total USGS depth uncertainty. Never relabel the source survey as NAD83(2011) merely because that point request succeeds."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / "var/review/estero-2012-vdatum-frame-review.json")
    p.add_argument("--expect-current-gates", action="store_true", help="Fail if reviewed frame acceptance changes")
    args = p.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    statuses = {sample["requested_horizontal_frame"]: sample["status"] for sample in result["samples"]}
    print(statuses)
    if args.expect_current_gates and statuses != {
        "NAD83_CORS96": "rejected", "NAD83_2011": "point_available",
        "NAD83_NSRS2007": "rejected", "WGS84_G1150": "rejected"
    }:
        raise SystemExit("VDatum frame availability changed; review before source promotion")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check public CIAP ROV WFS layers without converting them to fishing marks.

The Central 2016 video layer carries timecoded positions, not fish detections.
The separate fish layer is an aggregated display layer. Keep these distinct.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE = "https://data.axds.co/gs"
LAYERS = {
    "central_video": ("ciap_seafloor", "ciap_seafloor:cruise_e_videopoints"),
    "fish_display": ("ciap_hex", "ciap_hex:fish_wms"),
}
OUTPUT = Path("research/receipts/ciap-2016-central-rov-public-service-audit.json")


def layer_url(workspace, layer):
    return f"{BASE}/{workspace}/wfs?" + urlencode({
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "outputFormat": "application/json", "typeName": layer, "maxFeatures": 2,
    })


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast source audit/1.0"}), timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"CIAP WFS HTTP {response.status}")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("CIAP bounded WFS probe exceeded 2 MB")
    return json.loads(raw)


def inspect_layer(payload, expected_fields):
    if payload.get("type") != "FeatureCollection" or payload.get("numberReturned") != 2:
        raise ValueError("CIAP WFS feature response incomplete")
    features = payload.get("features", [])
    if len(features) != 2 or payload.get("totalFeatures", 0) < 2:
        raise ValueError("CIAP WFS count or sample changed")
    properties = sorted(features[0].get("properties", {}))
    if not set(expected_fields).issubset(properties):
        raise ValueError("CIAP WFS required fields changed")
    if any(sorted(item.get("properties", {})) != properties for item in features):
        raise ValueError("CIAP WFS sample schema inconsistent")
    geometry_types = sorted({item.get("geometry", {}).get("type") for item in features})
    crs = payload.get("crs", {}).get("properties", {}).get("name")
    if geometry_types != ["Point"] or crs not in ("urn:ogc:def:crs:EPSG::4326", "urn:ogc:def:crs:EPSG::3857"):
        raise ValueError("CIAP WFS geometry or CRS changed")
    return {"total_features_reported": payload["totalFeatures"], "sample_property_fields": properties,
            "sample_geometry_types": geometry_types, "response_crs": crs}


def build(video, fish):
    video_info = inspect_layer(video, ("site", "location", "dive", "line", "survey_date", "lon", "lat", "video", "survey_timestamp"))
    fish_info = inspect_layer(fish, ("area_fish", "count", "taxa"))
    if video_info["response_crs"] != "urn:ogc:def:crs:EPSG::4326" or fish_info["response_crs"] != "urn:ogc:def:crs:EPSG::3857":
        raise ValueError("CIAP layer CRS changed")
    return {
        "schema_version": 1,
        "scope": "ciap-2016-central-public-wfs-service-access",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_documentation_url": "https://www.cencoos.org/wp-content/uploads/2024/02/Appendix-F1.5-Coastal-Impact-Assistance-Program-CIAP-ROV-Survey-State-of-California-Data-Stream-Plan.pdf",
        "central_video": {"url": layer_url(*LAYERS["central_video"]), **video_info,
                          "interpretation": "Timecoded 2016 cruise E video positions; not fish detections or independent substrate annotations."},
        "fish_display": {"url": layer_url(*LAYERS["fish_display"]), **fish_info,
                         "interpretation": "Aggregated fish-display features; not verified row-level fish observations or exact ROV bottom positions."},
        "original_row_level_fish_and_substrate_tables_retrieved": False,
        "position_uncertainty_verified": False,
        "independent_substrate_gate_satisfied": False,
        "biological_fish_gate_satisfied": False,
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
        "limitations": "WFS counts are server-reported historical layer totals; the audit intentionally omits sample coordinates and does not infer a 200–300 ft open-reference count. Obtain and review the original fish/substrate and effort tables, cleaned position error and sample roles before a candidate-scale join.",
    }


def stable(report):
    return {key: value for key, value in report.items() if key != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    report = build(fetch(layer_url(*LAYERS["central_video"])), fetch(layer_url(*LAYERS["fish_display"])))
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("CIAP ROV WFS layer changed; review before promotion")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Central video {report['central_video']['total_features_reported']}; fish display {report['fish_display']['total_features_reported']}; zero spots")


if __name__ == "__main__":
    main()

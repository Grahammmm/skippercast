#!/usr/bin/env python3
"""Prioritize original Monterey hard-bottom evidence near the 200–300 ft band.

This uses already audited native USGS pixels. NAVD88 elevations cannot be
treated as MLLW fishing depths, and an outline's min/max only establishes a
possible intersection with the band, not the number of qualifying cells.
"""

import argparse
import json
from pathlib import Path


LOWER_M = 200 * 0.3048
UPPER_M = 300 * 0.3048


def build(audit):
    if (audit.get("scope") != "original-usgs-bathymetry-vs-habitat-context"
            or audit.get("vertical_datum") != "NAVD88"
            or audit.get("mllw_conversion_reviewed") is not False
            or audit.get("product_uncertainty_grid_available") is not False
            or audit.get("fishing_target") is not False):
        raise ValueError("Unexpected Monterey source review or promotion state")
    rows = []
    for item in audit["outlines"]:
        depth = item.get("depth_m_below_navd88")
        if not depth or depth["maximum"] < LOWER_M or depth["minimum"] > UPPER_M:
            continue
        camera = item["historical_camera_interior_windows"]
        # Research order only: independent historical camera evidence first,
        # then original measured-cell support. Never interpret as fish rank.
        rows.append({
            "context_id": item["context_id"],
            "native_measured_cells_in_full_outline": item["native_measured_cells"],
            "native_measured_cells_in_200_300ft_band": None,
            "navd88_depth_range_m": [depth["minimum"], depth["maximum"]],
            "historical_camera_windows": camera,
            "historical_rock_boulder_windows": item["historical_rock_boulder_windows"],
            "historical_rockfish_positive_windows": item["historical_rockfish_positive_windows"],
            "priority_for_original_pixel_recheck": "camera-and-bottom" if camera else "bottom-only",
            "fishing_target": False,
            "exportable": False,
        })
    rows.sort(key=lambda row: (-row["historical_camera_windows"],
                               -row["native_measured_cells_in_full_outline"],
                               row["context_id"]))
    return {
        "schema_version": 1,
        "scope": "monterey-native-200-300ft-research-priority",
        "source_review_sha256": audit["bathymetry_sha256"],
        "native_vertical_datum": "NAVD88",
        "comparison_band_m_below_navd88": [round(LOWER_M, 3), round(UPPER_M, 3)],
        "source_outline_count": audit["context_outlines"],
        "possible_band_overlap_outline_count": len(rows),
        "historical_camera_overlap_outline_count": sum(bool(r["historical_camera_windows"]) for r in rows),
        "priority_order": rows,
        "fishing_target": False,
        "exportable": False,
        "next_required_work": [
            "Reopen the original GeoTIFF and count valid 200–300 ft NAVD88 cells inside each outline.",
            "Resolve horizontal realization/epoch and full-area NAVD88-to-MLLW conversion with transformation uncertainty.",
            "Obtain independent per-cell bathymetry uncertainty or a better original MLLW survey.",
            "Review original bottom classification, dated video positions, current protected areas, hazards and access before ranking any fishable patch.",
        ],
        "limitations": "A min/max range can intersect the comparison band even if no measured pixel within the outline actually lies in it. The band is NAVD88, not a verified 200–300 ft MLLW fishing depth. Camera windows are historical and do not prove current fish presence.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=Path("dist/data/usgs-offshore-monterey-bathy-context-review.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(json.loads(args.audit.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['possible_band_overlap_outline_count']} research outlines; zero fishing targets")


if __name__ == "__main__":
    main()

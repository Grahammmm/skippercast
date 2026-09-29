#!/usr/bin/env python3
"""Join independent Monterey 300 ft research receipts without promoting spots."""

import argparse
import json
from pathlib import Path


def build(paired, closure, enc):
    if (paired.get("scope") != "monterey-original-paired-hard-depth-band-audit"
            or closure.get("scope") != "monterey-original-300-research-closure-screen"
            or enc.get("scope") != "monterey-original-300-enc-danger-screen"
            or any(source.get("fishing_target") is not False for source in (paired, closure, enc))):
        raise ValueError("Unexpected original Monterey research receipt")
    by_closure = {row["context_id"]: row for row in closure["outlines"]}
    by_enc = {row["context_id"]: row for row in enc["outlines"]}
    if (len(by_closure) != paired["outline_count"] or len(by_enc) != paired["outline_count"]
            or set(by_closure) != set(by_enc)
            or set(by_closure) != {row["context_id"] for row in paired["outlines"]}):
        raise ValueError("Source reviews do not contain the same full outlines")
    rows = []
    for item in paired["outlines"]:
        ident = item["context_id"]
        mpa = by_closure[ident]
        hazard = by_enc[ident]
        if mpa["native_200_300ft_navd88_cells"] != item["native_navd88_band_cells"]:
            raise ValueError("Native depth counts diverged between screens")
        held = mpa["within_100m_closure_review_buffer"] or hazard["within_charted_danger_review_buffer"]
        rows.append({"context_id": ident,
                     "native_navd88_band_cells": item["native_navd88_band_cells"],
                     "paired_original_class3_hard_band_cells": item["paired_original_class3_hard_band_cells"],
                     "historical_camera_windows": item["historical_camera_windows"],
                     "historical_rockfish_positive_windows": item["historical_rockfish_positive_windows"],
                     "mapped_protected_area_or_gea_buffer": mpa["within_100m_closure_review_buffer"],
                     "mapped_enc_danger_buffer": hazard["within_charted_danger_review_buffer"],
                     "nearest_cdfw_mpa_m": mpa["nearest_cdfw_mpa_m"],
                     "nearest_noaa_gea_m": mpa["nearest_noaa_gea_m"],
                     "nearest_charted_danger_in_scope_m": hazard["nearest_charted_danger_in_scope_m"],
                     "research_hold": held,
                     "mllw_depth_qualified": False,
                     "source_uncertainty_qualified": False,
                     "fish_presence_verified_current": False,
                     "fishing_target": False, "exportable": False})
    ordered = sorted(rows, key=lambda row: (row["research_hold"],
                                             not bool(row["historical_camera_windows"]),
                                             -row["paired_original_class3_hard_band_cells"],
                                             row["context_id"]))
    return {"schema_version": 1, "scope": "monterey-300-source-evidence-review-matrix",
            "source_checks": {"paired_at": paired["audited_at"], "cdfw_noaa_at": closure["audited_at"],
                              "enc_at": enc["audited_at"]},
            "outline_count": len(rows),
            "outlines_with_historical_camera_windows": sum(bool(row["historical_camera_windows"]) for row in rows),
            "outlines_without_mapped_100m_buffer_hits": sum(not row["research_hold"] for row in rows),
            "camera_outlines_without_mapped_100m_buffer_hits": sum(
                bool(row["historical_camera_windows"]) and not row["research_hold"] for row in rows),
            "review_order": ordered,
            "fishing_target": False, "exportable": False,
            "next_release_gates": [
                "Full-area NAVD88-to-MLLW conversion with source horizontal realization/epoch and NOAA VDatum uncertainty.",
                "Independent per-cell source depth uncertainty or a suitable original MLLW hydrographic survey.",
                "Candidate geometry rebuilt from exact qualified hard/depth cells, followed by fresh full-footprint legal/security/chart checks.",
                "Current species rules and access review, plus independent effort-based biological validation before predictive fish ranking.",
            ],
            "limitations": "Review order is for acquiring missing evidence, not a 1–3 fish rank, catch forecast, legal permission or chartplotter export. Historical video observations and approximate GIS clearance cannot substitute for current conditions or navigation review."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paired", type=Path, default=Path("dist/data/monterey-original-300-paired-review.json"))
    parser.add_argument("--closure", type=Path, default=Path("dist/data/monterey-original-300-closure-review.json"))
    parser.add_argument("--enc", type=Path, default=Path("dist/data/monterey-original-300-enc-review.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(*(json.loads(path.read_text()) for path in (args.paired, args.closure, args.enc)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['outlines_without_mapped_100m_buffer_hits']} research outlines without selected GIS buffer hits; zero fishing targets")


if __name__ == "__main__":
    main()

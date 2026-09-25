"""Prioritize original-grid habitat outlines for site review, without promotion.

This deterministic queue joins an original-cell depth receipt, a source-dated
habitat display layer, and a complete bounded ENC danger screen. It does not
approve navigation, legal take, fish presence, fishing targets or exports.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from skippercast.platform.contracts import atomic_json


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def triage(context: dict, depths: dict, enc: dict, profile: dict) -> dict:
    features = context.get("features", [])
    rows = depths.get("outlines", [])
    expected = profile["expected_outlines"]
    survey_id = profile["survey_id"]
    if len(features) != expected or len(rows) != expected:
        raise ValueError("Expected complete context and original-cell depth receipts")
    if (context.get("scope") != profile["context_scope"]
            or depths.get("scope") != profile["depth_scope"]
            or enc.get("scope_id") != profile["enc_scope"]
            or enc.get("queried_layers") != 18
            or enc.get("context_outlines_in_scope_by_survey") != {survey_id: expected}
            or enc.get("review_buffer_m") != profile["review_buffer_m"]):
        raise ValueError("Source identity or bounded chart review changed")
    if (depths.get("context_sha256") is None
            or context.get("source_screen_counts", {}).get("joined_cells_after_mpa_gea_historical_dton") != profile["expected_joined_cells_after_exclusions"]):
        raise ValueError("Native-cell source screen is missing or changed")
    feature_by_id = {f["properties"]["id"]: f for f in features}
    depth_by_id = {row["id"]: row for row in rows}
    if len(feature_by_id) != expected or set(feature_by_id) != set(depth_by_id):
        raise ValueError("Outline IDs are duplicate or incompletely joined")
    held = {row["context_id"] for row in enc.get("outlines_near_charted_dangers", [])}
    if (not held.issubset(feature_by_id)
            or len(held) != len(enc.get("outlines_near_charted_dangers", []))):
        raise ValueError("Chart review references unknown outlines")
    shortlist = []
    for id_, f in feature_by_id.items():
        p = f["properties"]
        d = depth_by_id[id_]
        z = d["sampled_original_depth_ft"]
        if (p.get("survey_id") != survey_id or p.get("fishing_target") is not False
                or p.get("exportable") is not False or d.get("fishing_target") is not False
                or d.get("exportable") is not False or p.get("depth_qualified_for_target") is not False):
            raise ValueError("Research outline was unexpectedly promoted")
        area = p["approx_display_area_m2"]
        relief = p["sampled_relief_5_95_m"]
        if (area < context["minimum_display_area_m2"] or relief < 0
                or z["minimum"] < 25 or z["maximum"] > profile["maximum_screened_depth_ft"]
                or d["qualified_original_cells"] < 1):
            raise ValueError("Original-cell measurements violate review scope")
        if (id_ in held or area < profile["minimum_display_area_m2"]
                or relief < profile["minimum_sampled_relief_5_95_m"]
                or z["median"] < profile["minimum_sampled_median_depth_ft"]):
            continue
        # Sorting key is transparent physical evidence, not catch likelihood.
        shortlist.append({
            "context_id": id_,
            "survey_id": survey_id,
            "display_area_m2": area,
            "sampled_relief_5_95_m": relief,
            "original_cell_depth_ft": z,
            "original_qualified_cells": d["qualified_original_cells"],
            "charted_danger_within_review_buffer": False,
            "fishing_target": False,
            "exportable": False,
        })
    shortlist.sort(key=lambda r: (-r["display_area_m2"], -r["sampled_relief_5_95_m"], r["context_id"]))
    return {
        "schema_version": 1,
        "scope": "original-habitat-site-review-queue",
        "profile_id": profile["id"],
        "survey_id": survey_id,
        "source_context_outlines": expected,
        "outlines_near_selected_chart_dangers": len(held),
        "research_shortlist_count": len(shortlist),
        "research_shortlist": shortlist,
        "selection": {"review_buffer_m": profile["review_buffer_m"],
                      "minimum_display_area_m2": profile["minimum_display_area_m2"],
                      "minimum_sampled_relief_5_95_m": profile["minimum_sampled_relief_5_95_m"],
                      "minimum_sampled_median_depth_ft": profile["minimum_sampled_median_depth_ft"],
                      "sort": "display area descending, relief descending, stable source ID",
                      "meaning": "Research priority only, not fishing quality or catch likelihood"},
        "enc_checked_at": enc["enc_checked_at"],
        "source_depth_reviewed_at": depths["reviewed_at"],
        "mpa_screened_at": context["mpa_screened_at"],
        "federal_screened_at": context["federal_screened_at"],
        "remaining_gates": [
            "Refresh and review complete current CDFW and federal exclusion geometry for each exact outline",
            "Inspect certified current chart, complete approach route and harbor/bar conditions",
            "Check species, date, method and possession rules at each exact coordinate",
            "Assess habitat evidence, current exposure and fish observations without treating historical rock as catch success",
        ],
        "fishing_target": False,
        "exportable": False,
        "limitations": "The historical polygons are inward display approximations, not complete rock boundaries. A 100 m miss in selected ENC Direct danger layers is not navigation clearance. The shortlist is a work queue, not a fishing recommendation or chartplotter layer.",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context", type=Path, default=Path("dist/data/cape-mendocino-native-hard-context.geojson"))
    p.add_argument("--depths", type=Path, default=Path("dist/data/h11975-research-outline-original-depths.json"))
    p.add_argument("--enc", type=Path, required=True)
    p.add_argument("--profile", type=Path, default=Path("catalog/original-habitat-triage-profiles.json"))
    p.add_argument("--profile-id", default="cape-mendocino-h11975")
    p.add_argument("--max-enc-age-hours", type=float, default=36)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    inputs = (a.context, a.depths, a.enc)
    profiles = json.loads(a.profile.read_text())["profiles"]
    profile = next((row for row in profiles if row["id"] == a.profile_id), None)
    if profile is None:
        raise ValueError("Unknown original-habitat triage profile")
    context, depths, enc = (json.loads(path.read_text()) for path in inputs)
    if _digest(a.context) != depths.get("context_sha256"):
        raise ValueError("Original-cell depth receipt does not match the published context")
    enc_time = datetime.fromisoformat(enc["enc_checked_at"].replace("Z", "+00:00"))
    enc_age = (datetime.now(timezone.utc) - enc_time).total_seconds() / 3600
    if enc_age < 0 or enc_age > a.max_enc_age_hours:
        raise ValueError("Bounded ENC danger review is stale or future-dated")
    result = triage(context, depths, enc, profile)
    result["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["input_sha256"] = {name: _digest(path) for name, path in zip(("context", "depths", "enc"), inputs)}
    result["profile_sha256"] = _digest(a.profile)
    atomic_json(a.output, result)
    print(json.dumps({"shortlist": result["research_shortlist_count"],
                      "charted_danger_buffer_holds": result["outlines_near_selected_chart_dangers"]}))


if __name__ == "__main__":
    main()

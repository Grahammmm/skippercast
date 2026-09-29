"""Prioritize original regular-BAG hard-bottom outlines for manual site review.

The result is a research queue, never a fishing recommendation or export.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from skippercast.platform.contracts import atomic_json


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def triage(context: dict, summary: dict, enc: dict, profile: dict, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    features = context.get("features", [])
    surveys = {row["survey_id"]: row for row in summary.get("surveys", [])}
    if (profile.get("status") != "research-priority-only"
            or context.get("scope") != profile["context_scope"]
            or summary.get("scope") != "native-noaa-usgs-review-summary"
            or context.get("source_review") != "data/" + profile["source_review_filename"]
            or len(features) != profile["expected_outlines"]
            or set(surveys) != set(profile["survey_ids"])):
        raise ValueError("Original regular-grid source identity or outline count changed")
    checked = datetime.fromisoformat(enc["enc_checked_at"].replace("Z", "+00:00"))
    if not 0 <= (now - checked).total_seconds() <= 36 * 3600:
        raise ValueError("Chart-danger review is stale")
    expected = Counter(f["properties"]["survey_id"] for f in features)
    if (enc.get("scope_id") != profile["enc_scope"]
            or enc.get("queried_layers") != 18
            or enc.get("review_buffer_m") != profile["review_buffer_m"]
            or enc.get("context_outlines_in_scope_by_survey") != dict(expected)):
        raise ValueError("Incomplete bounded ENC danger screen")
    held = {row["context_id"] for row in enc.get("outlines_near_charted_dangers", [])}
    ids = {f["properties"]["id"] for f in features}
    if len(ids) != len(features) or not held.issubset(ids):
        raise ValueError("Duplicate outlines or unknown chart-danger hold")
    shortlist = []
    for feature in features:
        props = feature["properties"]
        survey = surveys[props["survey_id"]]
        low, high = props["depth_ft_range"]
        if (props.get("fishing_target") is not False or props.get("exportable") is not False
                or props.get("depth_qualified_for_target") is not False
                or survey["noaa_bag_sha256"] != props["noaa_bag_sha256"]
                or not 0 < low <= high <= profile["maximum_original_depth_ft"]
                or not 0 < props["max_product_uncertainty_m"] <= 2
                or props["approx_display_area_m2"] < 0):
            raise ValueError("Original-cell provenance, depth or research-only gate changed")
        if props["id"] in held or props["approx_display_area_m2"] < profile["minimum_display_area_m2"]:
            continue
        shortlist.append({"context_id": props["id"], "survey_id": props["survey_id"],
                          "display_area_m2": props["approx_display_area_m2"],
                          "original_component_depth_ft_range": [low, high],
                          "maximum_original_product_uncertainty_m": props["max_product_uncertainty_m"],
                          "charted_danger_within_review_buffer": False,
                          "fishing_target": False, "exportable": False})
    shortlist.sort(key=lambda row: (-row["display_area_m2"], row["context_id"]))
    return {"schema_version": 1, "scope": "original-habitat-site-review-queue",
            "profile_id": profile["id"], "source_context_outlines": len(features),
            "outlines_near_selected_chart_dangers": len(held),
            "research_shortlist_count": len(shortlist), "research_shortlist": shortlist,
            "enc_checked_at": enc["enc_checked_at"],
            "mpa_screened_at": context["mpa_screened_at"],
            "federal_screened_at": context["federal_screened_at"],
            "built_at": now.isoformat(timespec="seconds"),
            "fishing_target": False, "exportable": False,
            "remaining_gates": ["Fresh complete CDFW MPA and NOAA GEA check at each exact outline",
                                "Certified current chart and complete approach route review",
                                "Current species/date/method regulations at the exact latitude and location",
                                "Present conditions and independently located fish evidence"],
            "limitations": "Area and component-wide depth ranges describe historical original cells, not local relief, fish abundance, a cleared route or a current safe fishing position."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--enc", type=Path, required=True)
    p.add_argument("--profiles", type=Path, default=Path("catalog/regular-habitat-triage-profiles.json"))
    p.add_argument("--profile-id", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    profiles = json.loads(args.profiles.read_text())["profiles"]
    profile = next((row for row in profiles if row["id"] == args.profile_id), None)
    if profile is None or args.summary.name != profile["source_review_filename"]:
        raise ValueError("Unknown profile or wrong original-cell review summary")
    paths = {"context": args.context, "summary": args.summary, "enc": args.enc}
    data = triage(*(json.loads(path.read_text()) for path in paths.values()), profile)
    data["input_sha256"] = {key: sha(path) for key, path in paths.items()}
    data["profile_sha256"] = sha(args.profiles)
    atomic_json(args.output, data)
    print(json.dumps({"profile": args.profile_id, "research_shortlist": data["research_shortlist_count"],
                      "charted_danger_holds": data["outlines_near_selected_chart_dangers"]}))


if __name__ == "__main__":
    main()

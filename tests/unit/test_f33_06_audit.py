"""F33-06: habitat triage checks the whole depth range and finite area/relief.

Contract protected: an outline enters the research shortlist only when its
original-cell depths are finite numbers with 25 <= minimum <= median <=
maximum <= the profile limit, and its area/relief are finite. Believable bug:
checking only the two endpoints lets a 900 ft median inside a 30-100 ft range
(or a NaN area, which a plain `<` test never rejects) reach the shortlist.
All data below is invented; nothing reads dist/, var/ or receipts.
"""
from datetime import datetime, timedelta, timezone

import pytest

from research.scripts.triage_original_habitat_outlines import triage as triage_original
from research.scripts.triage_regular_habitat_outlines import triage as triage_regular

NAN, INF = float("nan"), float("inf")

ORIGINAL_PROFILE = {
    "id": "synthetic", "survey_id": "SYN1", "context_scope": "ctx", "depth_scope": "dep",
    "enc_scope": "enc", "expected_outlines": 1, "expected_joined_cells_after_exclusions": 5,
    "review_buffer_m": 100, "minimum_display_area_m2": 4000,
    "minimum_sampled_relief_5_95_m": 2, "minimum_sampled_median_depth_ft": 40,
    "maximum_screened_depth_ft": 200,
}


def original_packet(minimum=50.0, median=80.0, maximum=120.0, area=5000.0, relief=3.0):
    context = {
        "scope": "ctx", "minimum_display_area_m2": 100, "mpa_screened_at": "t",
        "federal_screened_at": "t",
        "source_screen_counts": {"joined_cells_after_mpa_gea_historical_dton": 5},
        "features": [{"properties": {
            "id": "o1", "survey_id": "SYN1", "fishing_target": False, "exportable": False,
            "depth_qualified_for_target": False, "approx_display_area_m2": area,
            "sampled_relief_5_95_m": relief}}],
    }
    depths = {
        "scope": "dep", "context_sha256": "x", "reviewed_at": "t",
        "outlines": [{"id": "o1", "fishing_target": False, "exportable": False,
                      "qualified_original_cells": 3,
                      "sampled_original_depth_ft": {
                          "minimum": minimum, "median": median, "maximum": maximum}}],
    }
    enc = {"scope_id": "enc", "queried_layers": 18, "review_buffer_m": 100,
           "context_outlines_in_scope_by_survey": {"SYN1": 1},
           "outlines_near_charted_dangers": [], "enc_checked_at": "t"}
    return context, depths, enc


def test_original_valid_range_is_shortlisted_with_order_preserved():
    result = triage_original(*original_packet(), ORIGINAL_PROFILE)
    assert result["research_shortlist_count"] == 1
    z = result["research_shortlist"][0]["original_cell_depth_ft"]
    assert z["minimum"] <= z["median"] <= z["maximum"]


@pytest.mark.parametrize("minimum,median,maximum", [(25, 40, 200), (25, 25, 25), (200, 200, 200)])
def test_original_boundary_values_are_accepted(minimum, median, maximum):
    # Median 25 sits below the 40 ft ranking cutoff: accepted as valid, then not ranked.
    result = triage_original(*original_packet(minimum, median, maximum), ORIGINAL_PROFILE)
    assert result["research_shortlist_count"] == (1 if median >= 40 else 0)


@pytest.mark.parametrize("minimum,median,maximum", [
    (30, 900, 100),    # the cited failure: endpoints pass a 200 ft screen, median does not
    (30, 20, 100),     # median below minimum
    (30, 150, 100),    # median above maximum
    (24.9, 50, 100),   # minimum below 25
    (30, 50, 200.1),   # maximum above the profile limit
    (60, 50, 40),      # reversed range
    (NAN, 50, 100), (30, NAN, 100), (30, 50, NAN), (30, 50, INF), (-INF, 50, 100),
    (30, None, 100), (30, "50", 100), (30, True, 100),
])
def test_original_bad_depth_range_is_rejected(minimum, median, maximum):
    with pytest.raises(ValueError, match="violate review scope"):
        triage_original(*original_packet(minimum, median, maximum), ORIGINAL_PROFILE)


@pytest.mark.parametrize("area,relief", [
    (NAN, 3.0), (INF, 3.0), (5000.0, NAN), (5000.0, INF), (-1.0, 3.0), (5000.0, -0.1),
    (None, 3.0),
])
def test_original_bad_area_or_relief_is_rejected(area, relief):
    with pytest.raises(ValueError, match="violate review scope"):
        triage_original(*original_packet(area=area, relief=relief), ORIGINAL_PROFILE)


REGULAR_PROFILE = {
    "id": "synthetic-regular", "status": "research-priority-only", "context_scope": "ctx",
    "source_review_filename": "s.json", "enc_scope": "enc", "survey_ids": ["SYN1"],
    "expected_outlines": 1, "review_buffer_m": 100, "minimum_display_area_m2": 2500,
    "maximum_original_depth_ft": 200,
}
NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def regular_packet(depth_range=(30.0, 100.0), area=5000.0, uncertainty=1.0):
    context = {
        "scope": "ctx", "source_review": "data/s.json", "mpa_screened_at": "t",
        "federal_screened_at": "t",
        "features": [{"properties": {
            "id": "r1", "survey_id": "SYN1", "fishing_target": False, "exportable": False,
            "depth_qualified_for_target": False, "noaa_bag_sha256": "h",
            "depth_ft_range": list(depth_range), "max_product_uncertainty_m": uncertainty,
            "approx_display_area_m2": area}}],
    }
    summary = {"scope": "native-noaa-usgs-review-summary",
               "surveys": [{"survey_id": "SYN1", "noaa_bag_sha256": "h"}]}
    enc = {"scope_id": "enc", "queried_layers": 18, "review_buffer_m": 100,
           "context_outlines_in_scope_by_survey": {"SYN1": 1},
           "outlines_near_charted_dangers": [],
           "enc_checked_at": (NOW - timedelta(hours=1)).isoformat()}
    return context, summary, enc


def test_regular_valid_and_boundary_values_are_accepted():
    for rng in [(30.0, 100.0), (0.1, 200), (200, 200)]:
        result = triage_regular(*regular_packet(rng), REGULAR_PROFILE, now=NOW)
        assert result["research_shortlist"][0]["original_component_depth_ft_range"] == list(rng)


@pytest.mark.parametrize("kwargs", [
    {"area": NAN}, {"area": INF}, {"area": -1.0}, {"area": None}, {"area": "5000"},
    {"depth_range": (NAN, 100.0)}, {"depth_range": (30.0, NAN)}, {"depth_range": (30.0, INF)},
    {"depth_range": (100.0, 30.0)}, {"depth_range": (30.0, 200.1)},
    {"uncertainty": NAN}, {"uncertainty": 2.1},
])
def test_regular_nonfinite_or_invalid_values_are_rejected(kwargs):
    with pytest.raises(ValueError, match="Original-cell provenance"):
        triage_regular(*regular_packet(**kwargs), REGULAR_PROFILE, now=NOW)

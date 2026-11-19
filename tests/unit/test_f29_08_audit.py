"""F29-08: a NOAA catalog hint is not a negative native review."""

import json

import pytest

from research.scripts import build_central_source_queue as queue

SECTOR = "synthetic-sector"
SID = "synthetic-survey"
OLD = "https://example.invalid/old_1m_MLLW.bag"
NEW = "https://example.invalid/new_2m_MLLW.bag"
REVIEW = "review.json"
POSITIVE = {"native_resolution_m": [2, 2], "sectors": {SECTOR: {"measured_native_cells": 7}}}


def evidence(root, urls, *, claim=None, deep=None, regular=None):
    surveyed = {SID: {"products": {"bag": urls}}}
    bindings = [{"survey_id": SID, "claim": claim, "sector_id": SECTOR,
                 "review_paths": [REVIEW]}] if claim else []
    reviews, sector_reviews = queue.depth_review_paths(root, bindings, surveyed)
    return queue.noaa_bag_evidence([SID], surveyed, SECTOR, reviews, sector_reviews,
                                   deep or {}, {}, regular or {}, {}, None)


@pytest.fixture
def review_root(tmp_path):
    (tmp_path / REVIEW).write_text(json.dumps({
        "source_url": OLD,
        "survey_id": SID,
        "scope": "original-regular-bag-300-depth-source-review",
        "vertical_datum": "MLLW",
        "fishing_target": False,
        "counts": {"measured_native_cells": 10, "eligible_25_300ft_cells_with_margin": 0},
        "sector_cell_center_screen": {
            "sector_id": SECTOR,
            "counts": {"nominal_200_300ft_cells_passing_300ft_uncertainty_margin": 0},
        },
    }))
    return tmp_path


def file_evidence(row):
    return row["noaa_bag_evidence_by_survey_and_url"][SID]


@pytest.mark.parametrize(("claim", "summary", "path_key", "old_status", "deep"), [
    pytest.param("no-eligible-25-300ft-anywhere", "noaa_original_300ft_depth_refutations",
                 "depth_refutation_path", "inspected-negative", None, id="regular-depth"),
    pytest.param("no-eligible-200-300ft-in-sector", "noaa_original_200_300ft_sector_refutations",
                 "sector_200_300ft_refutation_path", "unknown", None, id="sector-band-only"),
    pytest.param(None, "noaa_original_deepwater_300ft_refutations", "depth_refutation_path",
                 "inspected-negative", {SID: {"source_url": OLD, "native_refinements": {
                     "shallowest_depth_m_mllw": 100}}}, id="deepwater"),
])
def test_new_bag_invalidates_only_the_aggregate_refutation(review_root, claim, summary, path_key, old_status, deep):
    # A survey ID match used to dismiss the new URL based on the old URL's receipt.
    before = evidence(review_root, [OLD], claim=claim, deep=deep)
    assert [item["survey_id"] for item in before[summary]] == [SID]
    old = file_evidence(before)[OLD]
    assert old["status"] == old_status
    assert old[path_key] == ("dist/data/central-deep-original-300-refutation.json" if deep else REVIEW)

    after = evidence(review_root, [OLD, NEW], claim=claim, deep=deep)
    assert after[summary] == []
    assert after["noaa_coarse_or_unresolved_leads"] == [SID]
    assert after["noaa_native_audit_refuted_fine_hint"] == []
    assert after["noaa_filename_fine_grid_leads"] == []
    assert file_evidence(after) == {OLD: old, NEW: {"status": "unknown"}}

    inspected = evidence(review_root, [OLD, NEW], claim=claim, deep=deep, regular={NEW: POSITIVE})
    assert inspected[summary] == []
    assert inspected["noaa_filename_fine_grid_leads"] == [SID]
    assert file_evidence(inspected) == {OLD: old, NEW: {"status": "inspected-positive"}}


@pytest.mark.parametrize(("review", "status", "fine", "refuted"), [
    pytest.param({}, "unknown", [], [], id="no-native-receipt"),
    pytest.param({NEW: {"native_resolution_m": [2, 2]}}, "unknown", [], [], id="no-sector-screen"),
    pytest.param({NEW: {"native_resolution_m": [2, 2], "sectors": {}}},
                 "inspected-negative", [], [SID], id="native-screen-negative"),
    pytest.param({NEW: POSITIVE}, "inspected-positive", [SID], [], id="native-screen-positive"),
])
def test_fine_hint_needs_exact_file_native_evidence(tmp_path, review, status, fine, refuted):
    # Filename alone used to be reported as refuted, even without the checked URL in a native review.
    row = evidence(tmp_path, [NEW], regular=review)
    assert row["noaa_filename_fine_grid_leads"] == fine
    assert row["noaa_native_audit_refuted_fine_hint"] == refuted
    assert file_evidence(row) == {NEW: {"status": status}}


def test_duplicate_review_paths_cannot_stand_in_for_another_bag(review_root):
    # Two distinct paths containing one URL cannot count as two independently reviewed BAGs.
    duplicate = review_root / "duplicate.json"
    duplicate.write_bytes((review_root / REVIEW).read_bytes())
    surveyed = {SID: {"products": {"bag": [OLD, NEW]}}}
    bindings = [{"survey_id": SID, "claim": "no-eligible-25-300ft-anywhere",
                 "review_paths": [REVIEW, duplicate.name]}]
    with pytest.raises(ValueError, match="Unreviewed native depth receipt"):
        queue.depth_review_paths(review_root, bindings, surveyed)

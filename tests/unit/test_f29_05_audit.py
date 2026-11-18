"""F29-05: contradictory or duplicated outline rows are rejected, whatever their order."""
import importlib.util

import pytest

from tests._support import ROOT

SCRIPT = ROOT / "research/scripts/build_monterey_300_review_matrix.py"
spec = importlib.util.spec_from_file_location("build_monterey_300_review_matrix", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def receipts(held=True):
    paired = {"scope": "monterey-original-paired-hard-depth-band-audit", "fishing_target": False,
              "audited_at": "t", "outline_count": 1,
              "outlines": [{"context_id": "A", "native_navd88_band_cells": 5,
                            "paired_original_class3_hard_band_cells": 2,
                            "historical_camera_windows": 0, "historical_rockfish_positive_windows": 0}]}

    def closure_row(hit):
        return {"context_id": "A", "native_200_300ft_navd88_cells": 5,
                "within_100m_closure_review_buffer": hit, "nearest_cdfw_mpa_m": 1, "nearest_noaa_gea_m": 1}

    closure = {"scope": "monterey-original-300-research-closure-screen", "fishing_target": False,
               "audited_at": "t", "outlines": [closure_row(held)]}
    enc = {"scope": "monterey-original-300-enc-danger-screen", "fishing_target": False, "audited_at": "t",
           "outlines": [{"context_id": "A", "within_charted_danger_review_buffer": False,
                         "nearest_charted_danger_in_scope_m": 9}]}
    return paired, closure, enc, closure_row


def test_single_held_row_stays_held():
    paired, closure, enc, _ = receipts()
    report = module.build(paired, closure, enc)
    assert report["review_order"][0]["research_hold"] is True
    assert report["outlines_without_mapped_100m_buffer_hits"] == 0


def test_single_clear_row_is_clear():
    paired, closure, enc, _ = receipts(held=False)
    assert module.build(paired, closure, enc)["review_order"][0]["research_hold"] is False


@pytest.mark.parametrize("held_first", [True, False])
def test_conflicting_closure_rows_fail_in_either_order(held_first):
    paired, closure, enc, row = receipts()
    pair = [row(True), row(False)]
    closure["outlines"] = pair if held_first else pair[::-1]
    with pytest.raises(ValueError, match="duplicate or missing"):
        module.build(paired, closure, enc)


@pytest.mark.parametrize("which", ["paired", "enc"])
def test_duplicate_rows_in_other_inputs_fail(which):
    paired, closure, enc, _ = receipts()
    source = paired if which == "paired" else enc
    source["outlines"] = source["outlines"] * 2
    with pytest.raises(ValueError, match="duplicate or missing"):
        module.build(paired, closure, enc)


def test_missing_row_fails():
    paired, closure, enc, _ = receipts()
    enc["outlines"] = []
    with pytest.raises(ValueError, match="duplicate or missing"):
        module.build(paired, closure, enc)

import importlib.util

import pytest

from tests._support import ROOT
spec = importlib.util.spec_from_file_location("seafloor_status", ROOT / "research/scripts/seafloor_status.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    return {"input_hash": "synthetic-input", "reaches": [
        {"id": "one", "region": "fictional", "status": "habitat-screened",
         "tier1_km2": 2, "tier2_km2": 1, "selected_valid_km2": 2, "screen": {"status": "ready"}},
        {"id": "two", "region": "fictional", "status": "habitat-screened",
         "tier1_km2": 0, "tier2_km2": 0, "selected_valid_km2": 0, "screen": {"status": "ready"}}]}


def test_report_derives_counts_and_does_not_infer_publication():
    result = module.render(fixture())
    assert "| fictional | 2 | 1 | 1 |" in result
    assert "2.000000 | 1.000000 | Not verified" in result
    assert "Total reaches: 2" in result
    assert "zero selected survey area" in result


def test_missing_coverage_is_not_treated_as_zero():
    data = fixture()
    del data["reaches"][0]["selected_valid_km2"]
    with pytest.raises(ValueError, match="Missing or invalid"):
        module.render(data)


def test_manual_labels_old_pilot_and_routes_current_counts_to_ledger():
    text = (ROOT / "docs/seafloor.md").read_text()
    assert "Historical M4 pilot" in text
    assert "research/scripts/seafloor_status.py" in text
    assert "Only three of 46 Central Coast reaches are assessed." not in text

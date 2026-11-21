"""F29-03: range alone is not fishing qualification in the Central Coast ledger."""

import pytest

from research.scripts import build_central_coverage_ledger as ledger
from research.scripts import build_central_source_queue as queue
from tests._support import ROOT


SHALLOW_REGION = "santa-cruz-monterey-bay"
DEEP_REGION = "monterey-point-sur"
QUALIFIED = {"depth_qualified": True, "vertical_datum": "MLLW"}
REVIEWED = {**QUALIFIED, "depth_qualification": {"status": "reviewed"}}


def build_ledger(monkeypatch, tmp_path, targets_by_region, *, limit=300):
    read_receipt = ledger.read

    def read(path):
        relative = path.relative_to(tmp_path)
        if path.name in {"atlas.json", "coverage.json", "region.json"}:
            region = "morro-bay" if relative.as_posix() == "dist/data/atlas.json" else path.parent.name
            targets = targets_by_region.get(region, [])
            if path.name == "atlas.json":
                return {"targets": targets, "fishing_depth_limit_ft": limit}
            if path.name == "coverage.json":
                return {"region_id": region, "published_targets": len(targets), "needs": []}
            return {"name": "Synthetic region", "bounds": []}
        return read_receipt(ROOT / relative)

    monkeypatch.setattr(ledger, "read", read)
    return ledger.build(tmp_path)


@pytest.mark.parametrize(("depths", "evidence", "limit", "error"), [
    pytest.param([30, 60], {}, 300, "qualified depth evidence", id="range-only"),
    pytest.param([30, 60], {"depth_qualified": True}, 300, "qualified depth evidence", id="missing-datum"),
    pytest.param([30, 60], {**QUALIFIED, "vertical_datum": "unverified source datum"}, 300,
                 "qualified depth evidence", id="unverified-datum"),
    pytest.param([60, 30], QUALIFIED, 300, "depth patch", id="reversed-shallow-range"),
    pytest.param([290, 230], REVIEWED, 300, "depth patch", id="reversed-deep-range"),
    pytest.param([0, 60], QUALIFIED, 300, "depth patch", id="zero-lower-bound"),
    pytest.param([-1, 60], QUALIFIED, 300, "depth patch", id="negative-lower-bound"),
    pytest.param([True, 60], QUALIFIED, 300, "depth patch", id="boolean-is-not-a-depth"),
    pytest.param([30, float("inf")], QUALIFIED, 300, "depth patch", id="nonfinite-depth"),
    pytest.param([230, 290], {"depth_qualification": {"status": "reviewed"}}, 300,
                 "qualified depth evidence", id="review-status-alone"),
    pytest.param([230, 290], QUALIFIED, 300, "Unreviewed >200 ft target", id="deep-without-review"),
    pytest.param([230, 290], REVIEWED, 200, "Unreviewed >200 ft target", id="deep-exceeds-package-cap"),
])
def test_ledger_refuses_targets_without_qualified_depth(monkeypatch, tmp_path, depths, evidence, limit, error):
    target = {"neighborhood_depth_ft": depths, **evidence}
    with pytest.raises(ValueError, match=error):
        build_ledger(monkeypatch, tmp_path, {SHALLOW_REGION: [target]}, limit=limit)


def test_reviewed_deeper_only_region_is_not_a_gap_and_legacy_rows_stay_held(monkeypatch, tmp_path):
    held = {"neighborhood_depth_ft": [30, 60], "research_only": True,
            "depth_qualified": False, "vertical_datum": "unverified source datum"}
    result = build_ledger(monkeypatch, tmp_path, {
        SHALLOW_REGION: [{"neighborhood_depth_ft": [30, 200], **QUALIFIED}],
        DEEP_REGION: [{"neighborhood_depth_ft": [230, 300], **REVIEWED}],
        "morro-bay": [held],
    })
    rows = {row["region_id"]: row for row in result["regions"]}
    assert rows[DEEP_REGION]["qualified_targets_at_or_under_200ft"] == 0
    assert rows[DEEP_REGION]["qualified_targets_200_to_300ft"] == 1
    assert rows[DEEP_REGION]["fishing_coordinate_status"] == "qualified-reviewed"
    assert rows["morro-bay"]["legacy_research_candidates"] == 1
    assert rows["morro-bay"]["fishing_coordinate_status"] == "none-qualified"
    assert result["totals"]["qualified_targets_at_or_under_200ft"] == 1
    assert result["totals"]["qualified_targets_200_to_300ft"] == 1
    expected_gaps = [region for region in ledger.REGIONS if region not in {SHALLOW_REGION, DEEP_REGION}]
    read_receipt = queue.read
    ledger_path = ROOT / "dist/data/central-coverage-ledger-v1.json"
    monkeypatch.setattr(queue, "read", lambda path: result if path == ledger_path else read_receipt(path))
    assert (result["totals"]["regions_without_qualified_targets"], queue.build(ROOT)["region_gaps"]) == (
        len(expected_gaps), expected_gaps,
    )

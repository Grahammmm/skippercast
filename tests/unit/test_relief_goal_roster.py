"""Offline M9 acceptance oracle: expectations, not observed relief status."""

import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.relief.coast_coverage import load_regions
from tests._support import ROOT

ROSTER = ROOT / "docs/operations/fixtures/relief-goal-roster.json"


def assert_goal_roster(path: Path) -> None:
    roster = json.loads(path.read_text(encoding="utf-8"))
    regions = load_regions(ROOT)
    assert roster.keys() == {"schema_version", "required_evidence_per_release", "release_rows"}
    assert roster["schema_version"] == 1
    assert roster["required_evidence_per_release"] == {
        "reviewed_release": "required",
        "independently_verified_live_check": "required",
        "depth": {
            "target_ft": 300,
            "allowed_findings": ["reaches_target", "bounded_shortfall", "explicit_unknown"],
        },
    }, "each release needs review, independent live verification and honest 300 ft depth evidence"

    rows = roster["release_rows"]
    for row in rows:
        assert row.keys() <= {"release_id", "child_geographies"}, "release rows must be inert"
    release_ids = [row["release_id"] for row in rows]
    assert regions["islands"].keys().isdisjoint(release_ids), "islands must not have release rows"
    assert len(release_ids) == 16 and Counter(release_ids) == Counter(regions["release"].keys()), (
        "the roster must account for each of the 16 configured releases exactly once"
    )

    children = Counter(
        (row["release_id"], child_id)
        for row in rows
        for child_id in row.get("child_geographies", [])
    )
    assert children == Counter(("southern-california", child_id) for child_id in regions["islands"]), (
        "each island must appear once, under southern-california only"
    )


def test_checked_in_roster_matches_coast_loader():
    """Catch a stale release list, misplaced island, or weakened evidence requirements."""
    assert_goal_roster(ROSTER)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ("missing-child", "each island must appear once"),
        ("second-parent", "each island must appear once"),
        ("island-release-row", "islands must not have release rows"),
        ("duplicate-release", "configured releases exactly once"),
        ("missing-live-slot", "independent live verification"),
        ("observed-live-result", "release rows must be inert"),
    ],
)
def test_roster_rejects_incomplete_or_double_counted_evidence_matrix(tmp_path, edit, message):
    """Catch a dropped child, duplicate coverage, or live claims substituted for requirements."""
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    rows = roster["release_rows"]
    parent = next(row for row in rows if row["release_id"] == "southern-california")
    other = next(row for row in rows if row["release_id"] == "point-arguello-conception")
    child = "channel-islands-north"
    if edit == "missing-child":
        parent["child_geographies"].remove(child)
    elif edit == "second-parent":
        other["child_geographies"] = [child]
    elif edit == "island-release-row":
        other["release_id"] = child  # Keep 16 rows; the child is still nested too.
    elif edit == "duplicate-release":
        other["release_id"] = "morro-bay"  # Keep 16 rows but lose a distinct release.
    elif edit == "missing-live-slot":
        del roster["required_evidence_per_release"]["independently_verified_live_check"]
    elif edit == "observed-live-result":
        other["live_status"] = "PASS"
    else:
        pytest.fail(f"unknown roster mutation: {edit}")

    path = tmp_path / ROSTER.name
    path.write_text(json.dumps(roster), encoding="utf-8")
    with pytest.raises(AssertionError, match=message):
        assert_goal_roster(path)

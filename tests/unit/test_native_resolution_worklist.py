import pytest

from scripts.relief.native_resolution_worklist import build_worklist


MONTEREY, SANTA_CRUZ = "monterey-point-sur", "santa-cruz-monterey-bay"
ORIGINAL, NORMALIZED = "1" * 64, "2" * 64
STATUS = "missing_catalog_original_hash"


@pytest.fixture
def records():
    receipt = {"schema": "sc-c24-resolution-evidence/1", "originals": {ORIGINAL: {
        "source_id": "source-a", "catalog_resolution_status": STATUS, "reviewed_native_resolution_m": None,
        "memberships": [{"region": r, "selection_id": s, "normalized_grid_sha256": NORMALIZED}
                        for r, s in ((MONTEREY, "sample-a"), (SANTA_CRUZ, "sample-b"))],
    }}}
    sheet = {"original_sha256": ORIGINAL, "source_id": "source-a", "catalog_status": STATUS,
             MONTEREY: "sample-a", SANTA_CRUZ: "sample-b", "proposed_native_resolution_m": "",
             "reviewer_evidence_reference": ""}
    return receipt, sheet


def test_groups_once_by_original_and_leaves_review_fields_blank(records):
    # Grouping by regional selection would issue two jobs for the same original.
    receipt, sheet = records
    worklist = build_worklist(receipt, [sheet])
    assert worklist == [{
        "original_sha256": ORIGINAL, "source_id": "source-a", "catalog_status": STATUS,
        "memberships": {MONTEREY: ["sample-a"], SANTA_CRUZ: ["sample-b"]},
        "proposed_native_resolution_m": "", "reviewer_evidence_reference": "",
    }]


def test_rejects_normalized_grid_as_original(records):
    # The normalized grid key looks like a valid digest but points to derived bytes.
    receipt, sheet = records
    with pytest.raises(ValueError, match="not an original digest"):
        build_worklist(receipt, [{**sheet, "original_sha256": NORMALIZED}])


@pytest.mark.parametrize("mutation, message", [
    ({MONTEREY: "sample-b", SANTA_CRUZ: "sample-a"}, "worksheet mismatch"),
    ({"proposed_native_resolution_m": "4"}, "worksheet mismatch"),
])
def test_refuses_swapped_memberships_and_filled_in_value(records, mutation, message):
    # Total counts survive swapping regions; a filled value is not an unreviewed task.
    receipt, sheet = records
    with pytest.raises(ValueError, match=message):
        build_worklist(receipt, [{**sheet, **mutation}])


def test_refuses_missing_or_duplicate_original(records):
    # Quietly skipping missing/duplicate rows would change the human review queue.
    receipt, sheet = records
    with pytest.raises(ValueError, match="omits"):
        build_worklist(receipt, [])
    with pytest.raises(ValueError, match="duplicate worksheet original"):
        build_worklist(receipt, [sheet, sheet])

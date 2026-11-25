"""The preview must not turn source guesses into reviewed catalog data."""
import pytest

from scripts.relief.native_review_preview import preview

DIGEST = "a" * 64
MEMBERSHIPS = {"monterey-point-sur": ["source-m"], "santa-cruz-monterey-bay": ["source-s"]}


@pytest.fixture
def baseline():
    receipt = {"schema": "sc-c24-resolution-evidence/1", "originals": {DIGEST: {
        "source_id": "source", "catalog_resolution_status": "missing_catalog_value",
        "reviewed_native_resolution_m": None, "memberships": [
            {"region": region, "selection_id": ids[0]} for region, ids in MEMBERSHIPS.items()
        ]}}}
    worksheet = {"original_sha256": DIGEST, "source_id": "source", "catalog_status": "missing_catalog_value",
                 **{region: ids[0] for region, ids in MEMBERSHIPS.items()}, **proposal("", "")}
    return receipt, [worksheet]


def proposal(value, citation, digest=DIGEST):
    return {"original_sha256": digest, "proposed_native_resolution_m": value,
            "reviewer_evidence_reference": citation}


def test_cited_original_keeps_both_memberships_and_ignores_proposal_scope(baseline):
    # Catch regrouping by an edited region or selection instead of by the pinned original.
    row = proposal("0.75", "Original metadata, p. 2") | {"monterey-point-sur": "neighbor"}
    receipt, worksheet = baseline
    result = preview(receipt, worksheet, [row])
    assert result["eligible_proposals"] == 1
    assert result["originals"][0]["memberships"] == MEMBERSHIPS
    assert result["originals"][0]["preview_status"] == "proposal-only"
    assert result["originals"][0]["proposed_native_resolution_m"] == "0.75"
    assert result["originals"][0]["reviewer_evidence_reference"] == "Original metadata, p. 2"


@pytest.mark.parametrize("entries,reason", [
    ([proposal("", "")], "no-proposal"),
    ([proposal("0.75", "")], "missing-value-or-citation"),
    ([proposal("NaN", "Original metadata")], "invalid-resolution"),
    ([proposal("0.75", "A"), proposal("1", "B")], "conflicting-proposals"),
    ([proposal("0.75", "A"), proposal("0.75", "B")], "conflicting-proposals"),
])
def test_missing_invalid_or_conflicting_evidence_never_picks_a_winner(baseline, entries, reason):
    # Catch accepting defaults, non-finite values, or using first/last entry wins.
    receipt, worksheet = baseline
    result = preview(receipt, worksheet, entries)
    assert result["eligible_proposals"] == 0
    row = result["originals"][0]
    assert row["preview_status"] == "unresolved" and row["reasons"] == [reason]
    assert row["proposed_native_resolution_m"] == row["reviewer_evidence_reference"] == ""


def test_normalized_output_cannot_supply_original_resolution(baseline):
    # Catch accepting a different well-formed hash or falling back to region/source labels.
    receipt, worksheet = baseline
    with pytest.raises(ValueError, match="not an exact original digest"):
        preview(receipt, worksheet, [proposal("0.75", "A", digest="b" * 64)])

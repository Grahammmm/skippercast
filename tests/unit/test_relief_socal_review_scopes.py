"""Offline contract for the blank SoCal relief review checklist."""

import json
from collections import Counter

import pytest

from skippercast.platform.contracts import load_catalogs, load_region, read_json
from tests._support import ROOT

CHECKLIST = ROOT / "docs/operations/fixtures/relief-socal-review-scopes.json"
CHILD_IDS = (
    "santa-barbara-channel",
    "channel-islands-north",
    "santa-monica-palos-verdes",
    "san-pedro-orange-county",
    "san-diego",
    "outer-islands-borderland",
)
EVIDENCE_CHECKS = ("military_access_hold_check", "source_rights_evidence")


@pytest.fixture(scope="module")
def catalogs():
    return load_catalogs(ROOT)


def _check_scope(scope, umbrella, catalogs):
    child = load_region(scope["region_id"], ROOT, catalogs=catalogs)
    west, south, east, north = child["bounds"]
    parent_west, parent_south, parent_east, parent_north = umbrella["bounds"]
    contained = (
        parent_west <= west and parent_south <= south
        and east <= parent_east and north <= parent_north
    )
    assert scope["geographic_inclusion"] == (
        "contained" if contained else "not_contained"
    ), f"{child['id']}: geographic inclusion disagrees with region bounds"
    for check in EVIDENCE_CHECKS:
        assert scope.get(check) == {
            "state": "unresolved", "owner": None, "evidence_ref": None,
        }, f"{child['id']}: {check} must be an unresolved, empty review input"


def test_checklist_covers_exactly_the_six_child_regions():
    # A duplicate or a neighboring valid region must not stand in for a missing child.
    checklist = read_json(CHECKLIST)
    assert checklist["schema_version"] == 1
    assert checklist["umbrella_region_id"] == "southern-california"
    assert Counter(row["region_id"] for row in checklist["scopes"]) == Counter(CHILD_IDS)


@pytest.mark.parametrize("region_id", CHILD_IDS)
def test_committed_scope_resolves_with_geometry_and_empty_evidence(region_id, catalogs):
    # Catch stale config references or bounds, and any hold decision inferred from containment.
    checklist = read_json(CHECKLIST)
    umbrella = load_region(checklist["umbrella_region_id"], ROOT, catalogs=catalogs)
    scope = next(row for row in checklist["scopes"] if row["region_id"] == region_id)
    _check_scope(scope, umbrella, catalogs)


@pytest.mark.parametrize("check", EVIDENCE_CHECKS)
@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(None, id="omitted"),
        pytest.param({"state": "cleared", "owner": None, "evidence_ref": None}, id="cleared-by-geometry"),
        pytest.param({"state": "unresolved", "owner": "fixture reviewer", "evidence_ref": None}, id="owner-only"),
        pytest.param({"state": "unresolved", "owner": None, "evidence_ref": "fixture note"}, id="evidence-only"),
    ],
)
def test_containment_does_not_fill_either_evidence_check(tmp_path, catalogs, check, entry):
    # Both checks must reject omissions, clearance without evidence, and half-filled inputs.
    checklist = read_json(CHECKLIST)
    umbrella = load_region(checklist["umbrella_region_id"], ROOT, catalogs=catalogs)
    scope = next(row for row in checklist["scopes"] if row["region_id"] == "channel-islands-north")
    assert scope["geographic_inclusion"] == "contained"
    if entry is None:
        del scope[check]
    else:
        scope[check] = entry
    changed = tmp_path / "scope.json"
    changed.write_text(json.dumps(scope), encoding="utf-8")
    with pytest.raises(AssertionError, match=f"{check} must be an unresolved"):
        _check_scope(read_json(changed), umbrella, catalogs)


def test_region_reader_rejects_a_stale_child_id(tmp_path, catalogs):
    # A plausible label or a copied checklist row cannot make a missing config resolve.
    checklist = read_json(CHECKLIST)
    umbrella = load_region(checklist["umbrella_region_id"], ROOT, catalogs=catalogs)
    scope = dict(checklist["scopes"][0], region_id="fixture-missing-region")
    changed = tmp_path / "scope.json"
    changed.write_text(json.dumps(scope), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="fixture-missing-region/region.json"):
        _check_scope(read_json(changed), umbrella, catalogs)

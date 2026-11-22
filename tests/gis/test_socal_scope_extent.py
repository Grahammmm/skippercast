"""Offline controls for the tracked SoCal scope comparison."""

import json

from shapely.geometry import Polygon, box

from scripts.relief.socal_scope_extent import compare_scope_extent
from tests._support import ROOT

PARENT = "southern-california"
CHANNEL = "santa-barbara-channel"
SAN_DIEGO = "san-diego"


def region_box(region_id):
    config = ROOT / "regions" / region_id / "region.json"
    return box(*json.loads(config.read_text(encoding="utf-8"))["bounds"])


def test_parent_label_does_not_expand_child_footprint():
    # A report keyed by the evidence label alone would wrongly claim full parent extent.
    parent, channel, san_diego = map(region_box, (PARENT, CHANNEL, SAN_DIEGO))
    report = compare_scope_extent(ROOT, channel, evidence_region_id=PARENT)
    assert report.evidence_region_id == PARENT
    scopes = report.scopes
    assert set(scopes) == {PARENT, CHANNEL, SAN_DIEGO}
    assert scopes[PARENT].status == "partial"
    assert scopes[PARENT].intersection.equals(channel)
    assert scopes[PARENT].residual.equals(parent.difference(channel))
    assert scopes[CHANNEL].status == "full"
    assert scopes[CHANNEL].intersection.equals(channel)
    assert scopes[CHANNEL].residual.is_empty
    assert scopes[SAN_DIEGO].status == "no_overlap"
    assert scopes[SAN_DIEGO].intersection.is_empty
    assert scopes[SAN_DIEGO].residual.equals(san_diego)


def test_full_parent_footprint_is_clipped_independently_to_each_scope():
    # A checker capped at child extents can never recognize a complete parent;
    # one that just copies the input footprint will overstate child intersections.
    scopes = compare_scope_extent(ROOT, region_box(PARENT), evidence_region_id=PARENT).scopes
    for scope_id in (PARENT, CHANNEL, SAN_DIEGO):
        result = scopes[scope_id]
        assert result.status == "full", scope_id
        assert result.intersection.equals(region_box(scope_id)), scope_id
        assert result.residual.is_empty, scope_id


def test_absent_footprint_is_no_evidence_even_with_parent_label():
    # Treating None as a surveyed-but-empty footprint would conflate missing
    # evidence with a supplied footprint that lies outside the scope.
    scopes = compare_scope_extent(ROOT, None, evidence_region_id=PARENT).scopes
    for scope_id in (PARENT, CHANNEL, SAN_DIEGO):
        result = scopes[scope_id]
        assert result.status == "no_evidence", scope_id
        assert result.intersection.is_empty, scope_id
        assert result.residual.equals(region_box(scope_id)), scope_id


def test_hole_is_residual_even_when_footprint_has_full_parent_bounds():
    # Checking only the footprint's bounding box would hide an interior gap.
    parent = region_box(PARENT)
    gap = box(-119, 33, -118, 33.5)
    footprint = Polygon(parent.exterior.coords, [gap.exterior.coords])
    result = compare_scope_extent(ROOT, footprint).scopes[PARENT]
    assert result.status == "partial"
    assert result.intersection.equals(footprint)
    assert result.residual.equals(gap)

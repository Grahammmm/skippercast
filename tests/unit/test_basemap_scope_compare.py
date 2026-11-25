"""Scope comparison tests use the shapes of the retained C15 and C25 receipts."""

import pytest

from scripts.relief.basemap_scope_compare import compare


def sample(z, indexed):
    return {str(z): {"tile": [z, 1, 2], "indexed": indexed}}


def basemap(region, points):
    return {"region": region, "basemap": {"index": {"points": points}}}


def test_two_basemap_scopes_report_locations_not_survey_coverage():
    # Counting a tile as surveyed relief would incorrectly promote both scopes.
    indexes = {"schema": "sc-offline-c25/1", "north_c": [
        basemap("crescent-city", {"harbor": sample(14, True)}),
        basemap("trinidad-klamath", {"harbor": sample(14, False), "mad-river": sample(11, True)}),
    ]}
    builds = {"rows": [{"region": row["region"], "coverage": "not-built"} for row in indexes["north_c"]]}
    first, second = compare(indexes, builds)
    assert first["basemap_samples"] == [{"site": "harbor", "tile": [14, 1, 2], "indexed": True}]
    assert second["basemap_samples"] == [
        {"site": "harbor", "tile": [14, 1, 2], "indexed": False},
        {"site": "mad-river", "tile": [11, 1, 2], "indexed": True},
    ]
    assert all(row["relief_build"] is None and row["surveyed_extent"] == "not established" for row in (first, second))


def test_join_never_borrows_a_neighbor_build():
    # Matching by position rather than region would attach the neighbor's cells.
    indexes = {"schema": "sc-offline-c25/1", "north_c": [basemap("crescent-city", {"harbor": sample(14, True)})]}
    neighbor = {"region": "trinidad-klamath", "coverage": "terrain-only", "envelope_sha256": "a" * 64, "valid_cells": 12}
    assert compare(indexes, {"rows": [neighbor]})[0]["relief_build"] is None
    match = {**neighbor, "region": "crescent-city", "valid_cells": 8}
    row = compare(indexes, {"rows": [neighbor, match]})[0]
    assert row["relief_build"] == {"coverage": "terrain-only", "envelope_sha256": "a" * 64, "valid_cells": 8}
    assert row["surveyed_extent"] == "not established"
    with pytest.raises(ValueError, match="duplicate region"):
        compare(indexes, {"rows": [neighbor, match, match]})


def test_sample_cannot_claim_a_different_zoom():
    # A tile returned for another zoom is not evidence for the requested zoom.
    indexes = {"schema": "sc-offline-c25/1", "north_c": [basemap("crescent-city", {
        "harbor": {"14": {"tile": [13, 1, 2], "indexed": True}},
    })]}
    with pytest.raises(ValueError, match="invalid basemap sample"):
        compare(indexes, {"rows": []})

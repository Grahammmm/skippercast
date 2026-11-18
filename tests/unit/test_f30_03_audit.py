"""F30-03: a habitat rebuild must replace only its own bottom-index rows."""
import pytest

from research.scripts.build_socal_habitat import install_bottom_views
from skippercast.platform.contracts import atomic_json, read_json

IDENTITY = {"schema_version": 1, "region_id": "southern-california"}
HABITAT = "SCI-HAB-000000000001"
RETIRED = "SCI-HAB-000000000002"
QUALIFIED = "SCI-Q-0000000003"


def habitat_source(filename, digest):
    return {"source_id": "fixture-merged", "archive_member": f"CINMS_bathy_merge_2024/{filename}",
            "sha256": digest * 64}


def test_habitat_install_refreshes_owned_rows_and_preserves_other_views(tmp_path):
    # An index replacement loses the qualified rows; an unrestricted union keeps retired rows.
    output, staged = tmp_path / "bottom", tmp_path / "staged"
    qualified_tile = {"target_id": QUALIFIED, "source_id": "fixture-survey"}
    tile_path = output / f"{QUALIFIED}.json"
    tile_receipt = atomic_json(tile_path, qualified_tile)
    qualified_bytes = tile_path.read_bytes()
    qualified_view = {"status": "surveyed", "source_id": "fixture-survey", **tile_receipt,
                      "path": f"regions/southern-california/bottom/{QUALIFIED}.json"}
    # Having the same source ID does not make a separately keyed source row habitat-owned.
    foreign_sources = {"fixture-survey": {"source_id": "fixture-survey", "sha256": "a" * 64},
                       "alternate": {"source_id": "fixture-merged", "sha256": "b" * 64}}
    index_path = output / "index.json"
    atomic_json(index_path, {**IDENTITY,
        "views": {QUALIFIED: qualified_view, RETIRED: {"status": "unavailable", "reason": "retired"},
                  HABITAT: {"status": "unavailable", "reason": "old"}},
        "sources": {"current.tif": habitat_source("current.tif", "c"),
                    "retired.tif": habitat_source("retired.tif", "d"), **foreign_sources}})

    habitat_tile = {"target_id": HABITAT, "source_id": "fixture-merged"}
    habitat_receipt = atomic_json(staged / f"{HABITAT}.json", habitat_tile)
    refreshed_view = {"status": "surveyed", "source_id": "fixture-merged", **habitat_receipt,
                      "path": f"regions/southern-california/bottom/{HABITAT}.json"}
    fragment = {**IDENTITY, "views": {HABITAT: refreshed_view},
                "sources": {"current.tif": habitat_source("current.tif", "e")}}
    atomic_json(staged / "index.json", fragment)

    install_bottom_views(staged, output, fragment)
    merged = read_json(index_path)
    assert merged == {**IDENTITY, "views": {QUALIFIED: qualified_view, HABITAT: refreshed_view},
                      "sources": {**foreign_sources, **fragment["sources"]}}
    assert tile_path.read_bytes() == qualified_bytes
    assert (output / f"{HABITAT}.json").read_bytes() == (staged / f"{HABITAT}.json").read_bytes()

    merged_bytes = index_path.read_bytes()
    install_bottom_views(staged, output, fragment)
    assert index_path.read_bytes() == merged_bytes


def test_source_filename_collision_is_refused_before_installing_tiles(tmp_path):
    # An unrelated source using the refreshed filename must not be overwritten.
    output, staged = tmp_path / "bottom", tmp_path / "staged"
    index_path = output / "index.json"
    atomic_json(index_path, {**IDENTITY, "views": {},
                             "sources": {"current.tif": {"source_id": "other-survey"}}})
    prior_bytes = index_path.read_bytes()
    fragment = {**IDENTITY, "views": {}, "sources": {"current.tif": habitat_source("current.tif", "f")}}
    atomic_json(staged / f"{HABITAT}.json", {"target_id": HABITAT})

    with pytest.raises(ValueError, match="source filename collides"):
        install_bottom_views(staged, output, fragment)
    assert index_path.read_bytes() == prior_bytes
    assert not (output / f"{HABITAT}.json").exists()

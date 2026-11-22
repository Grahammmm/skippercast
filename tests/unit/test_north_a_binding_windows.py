"""Pin the offline North A review frames, not source bindings or cameras."""

import json

import pytest

from skippercast.platform.contracts import read_json
from tests._support import ROOT

MANIFEST = ROOT / "docs/operations/fixtures/north-a-binding-windows.json"
NORTH_A = ("point-arena-bodega", "bodega-point-reyes", "point-reyes-pigeon")


def _assert_review_windows(path, expected_bounds):
    manifest = read_json(path)
    # Keep this a geometry-only fixture, not a place to add binding or camera fields.
    assert {key: value for key, value in manifest.items() if key != "regions"} == {
        "purpose": "binding-review-only",
        "crs": "EPSG:4326",
        "coordinate_order": ["west", "south", "east", "north"],
    }
    assert manifest["regions"].keys() == expected_bounds.keys()
    for release_id, bounds in expected_bounds.items():
        assert manifest["regions"][release_id] == {"fishing_bounds": bounds}, (
            f"{release_id}: expected exact fishing_bounds {bounds}"
        )


def test_manifest_matches_tracked_fishing_bounds_by_release_id():
    # Catches a stale copy or a window taken from the wider region bounds.
    configs = [read_json(ROOT / "regions" / release_id / "region.json") for release_id in NORTH_A]
    assert tuple(config["id"] for config in configs) == NORTH_A
    _assert_review_windows(MANIFEST, {config["id"]: config["fishing_bounds"] for config in configs})


def test_adjacent_review_windows_share_an_edge_without_merging():
    # Catches coarsening both the manifest and configs into overlapping frames.
    regions = read_json(MANIFEST)["regions"]
    for north, south in zip(NORTH_A, NORTH_A[1:]):
        nw, ns, ne, nn = regions[north]["fishing_bounds"]
        sw, ss, se, sn = regions[south]["fishing_bounds"]
        assert ss < sn == ns < nn and max(nw, sw) < min(ne, se), (north, south)


@pytest.fixture
def synthetic_review_windows(tmp_path):
    # Same width and height, different positions, sharing horizontal edges.
    expected = {
        release_id: [-124, south, -123, south + 1]
        for release_id, south in zip(NORTH_A, (39, 38, 37))
    }
    manifest = read_json(MANIFEST)
    manifest["regions"] = {
        release_id: {"fishing_bounds": bounds.copy()} for release_id, bounds in expected.items()
    }
    path = tmp_path / MANIFEST.name
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _assert_review_windows(path, expected)
    return path, manifest, expected


def test_equal_sized_windows_swapped_between_releases_are_rejected(synthetic_review_windows):
    # An unordered set or size-only comparison would accept the same boxes under the wrong IDs.
    path, manifest, expected = synthetic_review_windows
    _, middle, south = NORTH_A
    windows = manifest["regions"]
    windows[middle], windows[south] = windows[south], windows[middle]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError, match=f"{middle}: expected exact fishing_bounds"):
        _assert_review_windows(path, expected)


def test_larger_union_replacing_one_release_window_is_rejected(synthetic_review_windows):
    # A containment-only comparison would accept the middle window widened into its neighbor.
    path, manifest, expected = synthetic_review_windows
    _, middle, _ = NORTH_A
    manifest["regions"][middle]["fishing_bounds"] = [-124, 37, -123, 39]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError, match=f"{middle}: expected exact fishing_bounds"):
        _assert_review_windows(path, expected)

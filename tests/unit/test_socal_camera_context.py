import json
import shutil

import pytest

from scripts.relief import socal_camera_context as context
from tests._support import ROOT


def test_checked_in_cameras_keep_umbrella_release_and_distinct_children(monkeypatch, capsys):
    # A broad SoCal tag, name-based inference, or promoting a hit to a release
    # loses the distinct island matches or misses the separate border camera.
    monkeypatch.setenv("SKIPPERCAST_ROOT", str(ROOT))
    assert context.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["release_id"] == "southern-california"
    assert [(row["id"], row["contributors"]) for row in report["cameras"]] == [
        ("san-diego-reference-harbor-z13", ["san-diego"]),
        ("border-z15", ["san-diego"]),
        ("channel-islands-north-z13", ["channel-islands-north"]),
        ("outer-islands-borderland-z13", ["outer-islands-borderland"]),
    ]
    recipe = json.loads((ROOT / "regions/southern-california/render.json").read_text())
    assert [{k: v for k, v in row.items() if k != "contributors"}
            for row in report["cameras"]] == recipe["previews"]


@pytest.fixture
def config_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("SKIPPERCAST_ROOT", str(tmp_path))
    cameras = [
        {"id": "overlap", "center": [-119.5, 34], "size_m": 4000, "zoom": 13},
        {"id": "outside", "center": [-119.5, 35], "size_m": 4000, "zoom": 13},
        {"id": "edge", "center": [-120.5, 34], "size_m": 4000, "zoom": 13},
    ]
    documents = {
        "regions/southern-california/render.json": {
            "schema": "sc-render/1", "region": "southern-california", "style": "nearshore-v1.0.0",
            "previews": cameras, "piers": [],
        },
        "regions/channel-islands-north/region.json": {
            "id": "channel-islands-north", "bounds": [-120.5, 33.5, -119, 34.5],
            "fishing_bounds": [-120.4, 33.6, -119.8, 34.4],
        },
        "regions/outer-islands-borderland/region.json": {
            "id": "outer-islands-borderland", "bounds": [-120, 33, -118, 34.2],
        },
        "regions/san-diego/region.json": {"id": "san-diego", "bounds": [-118, 32.5, -117, 33.4]},
    }
    for relative, document in documents.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
    for relative in ("schemas/sc-render-v1.schema.json", "style/index.json"):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    return tmp_path


def test_center_projection_keeps_all_hits_and_empty_hits(config_tree):
    # First-match wins (or using fishing_bounds) drops an overlap contributor;
    # testing longitude alone matches the outside camera, and strict bounds lose the edge.
    report = context.camera_context()
    assert report["release_id"] == "southern-california"
    assert [(row["id"], row["contributors"]) for row in report["cameras"]] == [
        ("overlap", ["channel-islands-north", "outer-islands-borderland"]),
        ("outside", []),
        ("edge", ["channel-islands-north"]),
    ]


def test_missing_child_is_not_a_geographic_miss(config_tree):
    # Missing input must not look like a proven one-child match for the overlap.
    (config_tree / "regions/outer-islands-borderland/region.json").unlink()
    with pytest.raises(FileNotFoundError, match="outer-islands-borderland"):
        context.camera_context()


def test_missing_recipe_does_not_invent_a_preview(config_tree):
    # The normal preview reader has a valid fallback, which isn't a review camera.
    parent = config_tree / "regions/southern-california"
    (parent / "render.json").unlink()
    (parent / "region.json").write_text('{"fishing_bounds": [-121, 32, -117, 35]}', encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="Expected configured render recipe"):
        context.camera_context()

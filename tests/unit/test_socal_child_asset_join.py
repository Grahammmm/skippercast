import json

import pytest

from scripts.relief import socal_child_asset_join as join
from tests._support import ROOT

NORTH = "channel-islands-north"
OUTER = "outer-islands-borderland"
NORTH_CAMERA = "channel-islands-north-z13"
OUTER_CAMERA = "outer-islands-borderland-z13"
MAINLAND_CAMERA = "san-diego-reference-harbor-z13"


@pytest.fixture
def saved_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SKIPPERCAST_ROOT", str(ROOT))
    metadata = tmp_path / "qa-assets.json"

    def report(*assets):
        metadata.write_text(json.dumps({"assets": assets}), encoding="utf-8")
        assert join.main([str(metadata)]) == 0
        output = json.loads(capsys.readouterr().out)
        return output["release_id"], {
            (row["camera_id"], row["child_id"]): row["asset_ids"] for row in output["rows"]
        }

    return report


def asset(camera_id, child_id, asset_id):
    return {"camera_id": camera_id, "child_id": child_id, "asset_id": asset_id}


def test_swapped_island_provenance_then_matching_records(saved_report):
    # Joining by camera alone (or by child alone) would credit both swapped
    # records. Correcting just the provenance must credit each original asset.
    north = asset(NORTH_CAMERA, OUTER, "synthetic-a")
    outer = asset(OUTER_CAMERA, NORTH, "synthetic-b")
    _, rows = saved_report(outer, north)
    assert rows[NORTH_CAMERA, NORTH] == []
    assert rows[OUTER_CAMERA, OUTER] == []

    release_id, rows = saved_report(dict(outer, child_id=OUTER), dict(north, child_id=NORTH))
    assert release_id == "southern-california"
    assert rows[NORTH_CAMERA, NORTH] == ["synthetic-a"]
    assert rows[OUTER_CAMERA, OUTER] == ["synthetic-b"]


def test_mainland_cannot_fill_a_missing_island_asset(saved_report):
    # A release-wide or same-zoom fallback would reuse the valid mainland asset.
    _, rows = saved_report(asset(MAINLAND_CAMERA, "san-diego", "synthetic-mainland"))
    assert rows[MAINLAND_CAMERA, "san-diego"] == ["synthetic-mainland"]
    assert rows[NORTH_CAMERA, NORTH] == []
    assert rows[OUTER_CAMERA, OUTER] == []


def test_camera_id_is_not_a_prefix_match(saved_report):
    # Even the correct child tag cannot turn a near-match ID into evidence.
    _, rows = saved_report(asset(f"{NORTH_CAMERA}-alternate", NORTH, "synthetic-alternate"))
    assert rows[NORTH_CAMERA, NORTH] == []

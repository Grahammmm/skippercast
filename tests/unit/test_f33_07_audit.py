"""F33-07: discovery across a coast seam is separate from inventory."""

import json
from collections import Counter

import pytest

pytestmark = pytest.mark.gis


def coast_fixture():
    from shapely.geometry import box, mapping

    # Invented bands that meet at y=0. The crossing polygon's centroid is north.
    bands = {"central": (-4, 0), "north": (0, 4)}
    coasts = {"regions": [{"id": coast, "latitude": limits} for coast, limits in bands.items()]}
    extents = {coast: box(-4, lo, 4, hi) for coast, (lo, hi) in bands.items()}

    def feature(ident, geometry):
        return {"type": "Feature", "properties": {
            "id": ident, "metadata_url": "https://example.invalid/metadata", "source_year": 2000,
            "fishing_target": False, "exportable": False, "depth_qualified": False,
        }, "geometry": mapping(geometry)}

    cross = feature("cross", box(0, -1, 2, 3))
    single = feature("single", box(-2, -3, -1, 0))  # touches north but has no area there
    data = {"type": "FeatureCollection", "scope": "generalized-statewide-usgs-hard-bottom-context",
            "features": [cross, single]}
    owners = {"central": [single], "north": [cross]}
    # Hand-authored pieces: area 2 central, area 6 north, one canonical ID.
    views = {"central": [feature("cross", box(0, -1, 2, 0)), single],
             "north": [feature("cross", box(0, 0, 2, 3))]}
    return data, coasts, extents, owners, views


def assert_coast_contract(data, extents, inventory, candidates):
    from shapely.geometry import shape

    assert Counter(row["properties"]["id"] for rows in inventory.values() for row in rows) == {
        "cross": 1, "single": 1,
    }
    views = {}
    for coast, extent in extents.items():
        rows = candidates[coast]
        assert Counter(row["properties"]["id"] for row in rows) == (
            {"cross": 1, "single": 1} if coast == "central" else {"cross": 1}
        ), f"{coast}: regional discovery must include each intersecting feature once"
        views[coast] = {row["properties"]["id"]: shape(row["geometry"]) for row in rows}
        assert all(geometry.area > 0 and extent.covers(geometry) for geometry in views[coast].values())
        assert rows[0]["properties"] == data["features"][0]["properties"]

    cross, single = [shape(row["geometry"]) for row in data["features"]]
    central, north = (views[coast]["cross"] for coast in ("central", "north"))
    assert (central.area, north.area) == (2, 6)
    assert central.union(north).equals(cross)
    assert central.intersection(north).area == 0
    assert views["central"]["single"].equals(single)
    assert candidates["central"][1] == data["features"][1]


def test_reference_discovery_preserves_canonical_inventory():
    data, _, extents, owners, views = coast_fixture()
    assert_coast_contract(data, extents, owners, views)


def test_shards_separate_clipped_views_from_canonical_inventory(tmp_path, monkeypatch, capsys):
    # A centroid-only regression hides cross from central; copying the full
    # polygon instead of clipping it would double-count area at the seam.
    from research.scripts import split_usgs_context as splitter

    data, coasts, extents, owners, _ = coast_fixture()
    source, bands = tmp_path / "source.json", tmp_path / "bands.json"
    source.write_text(json.dumps(data))
    bands.write_text(json.dumps(coasts))
    monkeypatch.setattr("sys.argv", ["split_usgs_context", "--input", str(source), "--coasts",
                                    str(bands), "--output-dir", str(tmp_path)])
    splitter.main()
    assert capsys.readouterr().out.splitlines() == ["central 1", "north 1"]
    shards = {coast: json.loads((tmp_path / f"usgs-hard-context-{coast}.geojson").read_text())
              for coast in extents}
    inventory = {coast: shard["features"] for coast, shard in shards.items()}
    candidates = {coast: shard.get("regional_features", shard["features"]) for coast, shard in shards.items()}
    assert {coast: json.dumps(rows) for coast, rows in inventory.items()} == {
        coast: json.dumps(rows) for coast, rows in owners.items()
    }
    assert_coast_contract(json.loads(source.read_text()), extents, inventory, candidates)


def test_central_builder_reads_local_view_and_legacy_receipt(tmp_path, monkeypatch):
    # The sharder alone cannot fix the omission if the reader still uses the inventory.
    from research.scripts import build_central_habitat_context as habitat
    from research.scripts.split_usgs_context import split

    data, coasts, _, _, _ = coast_fixture()
    shard = split(data, coasts)["central"]
    region_id = "fixture-region"
    relative = f"regions/{region_id}/survey-habitat.geojson"
    region = {"status": "preview", "name": "Fixture", "fishing_bounds": [-4, -4, 4, 0],
              "assets": {"survey_habitat": relative, "protected_areas": "closures.json"},
              "mpa": {"minimum_features": 0}}
    destination = tmp_path / "dist" / relative
    destination.parent.mkdir(parents=True)
    config = tmp_path / "regions" / region_id / "region.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(region))
    (tmp_path / "dist" / "closures.json").write_text('{"type":"FeatureCollection","features":[]}')
    monkeypatch.setattr(habitat, "ROOT", tmp_path)
    monkeypatch.setattr(habitat, "read", lambda path: json.loads((tmp_path / path).read_text()))
    monkeypatch.setattr(habitat, "TO_METERS", lambda x, y: (float(x) * 100, float(y) * 100))
    monkeypatch.setattr(habitat, "TO_WGS84", lambda x, y: (float(x) / 100, float(y) / 100))

    for receipt, expected in [(shard, {"cross", "single"}),
                              ({key: value for key, value in shard.items() if key != "regional_features"}, {"single"})]:
        habitat.build_region(region_id, receipt, "fixture-digest")
        output = json.loads(destination.read_text())
        assert {row["properties"]["source_id"] for row in output["features"]} == expected
        assert all(row["properties"]["fishing_target"] is False for row in output["features"])

"""F32-01: refresh reapplies the reviewed conservative repair before comparing."""
import copy
import hashlib
import json

import pytest

pytest.importorskip("shapely")

from research.scripts import prepare_regional_mpas as prep
from research.scripts import refresh_reviewed_closures as refresh

REGION = "synthetic-region"
NAME = "Nested Special Closure"
URL = ("https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/"
       "biosds582_fpu/FeatureServer/0/query?x=1")
BOUNDS = [-1.0, -1.0, 10.0, 10.0]
OUTER = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
INNER = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]  # nested shell: invalid as a MultiPolygon
OTHER = [[6, 6], [7, 6], [7, 7], [6, 7], [6, 6]]


def feature(name, *rings):
    return {"type": "Feature", "properties": {"NAME": name},
            "geometry": {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}}


def response(*features, **extra):
    return {"type": "FeatureCollection", "features": list(features), **extra}


def raw_of(data):
    return json.dumps(data).encode()


@pytest.fixture
def pkg(tmp_path, monkeypatch):
    """Capture a snapshot with the real capture validation, then wire refresh to it."""
    config = {"id": REGION, "assets": {"protected_areas": f"regions/{REGION}/protected-areas.geojson"},
              "mpa": {"bounds": BOUNDS, "minimum_features": 2,
                      "conservative_union_invalid_names": [NAME]}}
    (tmp_path / "regions" / REGION).mkdir(parents=True)
    (tmp_path / "regions" / REGION / "region.json").write_text(json.dumps(config))
    original = response(feature(NAME, OUTER, INNER), feature("Plain", OTHER))
    captured = copy.deepcopy(original)
    prep.validate_response(captured, BOUNDS, 2, (NAME,))
    assert captured["features"][0]["properties"]["geometry_repair"]
    snapshot = dict(captured, region_id=REGION, source_url=URL, checked_at="2026-01-01T00:00:00Z",
                    verification_sha256=hashlib.sha256(raw_of(original)).hexdigest())
    path = tmp_path / "dist" / config["assets"]["protected_areas"]
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(snapshot))
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    return {"path": path, "original": original, "snapshot": snapshot, "serve": monkeypatch}


def run(pkg, data):
    pkg["serve"].setattr(refresh, "fetch", lambda url: raw_of(data))
    return refresh.refresh(REGION)


def saved(pkg):
    return json.loads(pkg["path"].read_text())


def test_unchanged_nested_shell_refreshes(pkg):
    # Positive control: the provider is unchanged, so the reviewed repair must match.
    result = run(pkg, pkg["original"])
    snap = saved(pkg)
    assert snap["checked_at"] != "2026-01-01T00:00:00Z"
    assert snap["verification_sha256"] == result["sources"][0]["sha256"]
    assert snap["verification_sha256"] == pkg["snapshot"]["verification_sha256"]  # original-source digest kept
    assert snap["features"] == json.loads(json.dumps(pkg["snapshot"]["features"]))


def test_raw_comparison_would_have_failed(pkg):
    # Negative control for the cited failure: the repaired snapshot differs from raw features.
    assert pkg["snapshot"]["features"] != pkg["original"]["features"]


def test_altered_footprint_is_held(pkg):
    data = copy.deepcopy(pkg["original"])
    data["features"][0]["geometry"]["coordinates"][0][0][2] = [5, 4]
    before = pkg["path"].read_text()
    with pytest.raises(ValueError, match="changed"):
        run(pkg, data)
    assert pkg["path"].read_text() == before


def test_missing_component_is_held(pkg):
    data = copy.deepcopy(pkg["original"])
    data["features"][0]["geometry"]["coordinates"].pop()  # drop the nested shell
    before = pkg["path"].read_text()
    with pytest.raises(ValueError):
        run(pkg, data)
    assert pkg["path"].read_text() == before


def test_unapproved_repair_is_held(pkg):
    data = copy.deepcopy(pkg["original"])
    data["features"][1] = feature("Unlisted Closure", OUTER, INNER)
    before = pkg["path"].read_text()
    with pytest.raises(ValueError):
        run(pkg, data)
    assert pkg["path"].read_text() == before


@pytest.mark.parametrize("where", ["top", "properties"])
def test_transfer_truncation_is_refused(pkg, where):
    data = copy.deepcopy(pkg["original"])
    if where == "top":
        data["exceededTransferLimit"] = True
    else:
        data["properties"] = {"exceededTransferLimit": True}
    before = pkg["path"].read_text()
    with pytest.raises(ValueError):
        run(pkg, data)
    assert pkg["path"].read_text() == before


def test_same_count_component_replacement_is_held(pkg):
    # Negative control: a different nested shell replaces the original one; union and count are unchanged.
    data = copy.deepcopy(pkg["original"])
    data["features"][0]["geometry"]["coordinates"][1] = [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
    fresh = copy.deepcopy(data)
    prep.validate_response(fresh, BOUNDS, 2, (NAME,))
    assert json.loads(json.dumps(fresh["features"])) == json.loads(json.dumps(pkg["snapshot"]["features"]))  # geometry check alone passes
    before = pkg["path"].read_text()
    with pytest.raises(ValueError, match="not verifiable"):
        run(pkg, data)
    assert pkg["path"].read_text() == before

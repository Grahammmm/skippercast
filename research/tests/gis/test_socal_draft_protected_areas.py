"""Draft closure receipts remain bounded, source-bound and unpublished."""
import hashlib
import json
from copy import deepcopy

import pytest
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape

from research.scripts.prepare_regional_mpas import source_url, validate_response
from tests._support import ROOT

REGIONS = {
    "santa-barbara-channel": 9, "channel-islands-north": 11,
    "santa-monica-palos-verdes": 2, "san-pedro-orange-county": 4,
    "san-diego": 5, "outer-islands-borderland": 6,
}
RECEIPTS = ROOT / "research/receipts"
GEA_PATH = "dist/regions/southern-california/groundfish-exclusions.geojson"
GEA_SHA = "5ee1dd67b937ac29108aa00a13256489fac359af6ec28db3f1223c2700239260"
BOLSA = "Bolsa Chica Basin SMCA (No-Take)"
STATEMENT = "MPA capture is not GEA coverage; GEA result from noaa-socal-gea only"


def load(path):
    return json.loads(path.read_text())


@pytest.mark.parametrize("rid,minimum", REGIONS.items())
def test_staged_mpas_and_gea_coverage(rid, minimum):
    region = load(ROOT / "regions" / rid / "region.json")
    snapshot_path = RECEIPTS / f"{rid}-protected-areas.geojson"
    snapshot = load(snapshot_path)
    assert snapshot_path.stat().st_size < 6_000_000
    assert snapshot["region_id"] == rid
    assert snapshot["source_url"] == source_url(region["mpa"]["bounds"])
    assert region["mpa"]["minimum_features"] == minimum
    allowed = region["mpa"].get("conservative_union_invalid_names", [])
    expected_repairs = {BOLSA} if rid == "san-pedro-orange-county" else set()
    assert set(allowed) == expected_repairs
    features = validate_response(snapshot, region["mpa"]["bounds"], minimum, tuple(allowed))
    assert len(features) >= minimum
    repaired = {f["properties"]["NAME"] for f in features
                if f["properties"].get("geometry_repair")}
    assert repaired == expected_repairs
    raw = snapshot["raw_receipt"]
    assert snapshot["checked_at"] == raw["retrieved_at"]
    assert snapshot["verification_sha256"] == raw["sha256"]
    assert len(raw["sha256"]) == 64 and int(raw["sha256"], 16) >= 0
    assert raw["http_status"] == 200 and 0 < raw["bytes"] <= 6_000_000
    assert raw["crs"] == "EPSG:4326" and raw["source_effective_date"] is None
    assert raw["rights"]["license"] == "CC-BY-4.0"
    assert raw["rights"]["attribution"] == "CDFW Marine Region GIS Lab"
    assert snapshot["staged_for"] == "dist/" + region["assets"]["protected_areas"]
    assert region["status"] == "draft"
    assert not (ROOT / "dist/regions" / rid).exists()
    gea = load(ROOT / GEA_PATH)
    selected = [f for f in gea["features"]
                if shape(f["geometry"]).intersects(box(*region["mpa"]["bounds"]))]
    expected_geas = {"West of Santa Barbara", "108/117 Bank", "Cherry Bank"} if rid == "outer-islands-borderland" else set()
    assert {f["properties"]["NAME"] for f in selected} == expected_geas
    assert gea["source_sha256"] == GEA_SHA
    coverage = load(RECEIPTS / "socal-draft-closure-coverage.json")["regions"][rid]
    assert coverage["mpa_count"] == len(features)
    assert coverage["mpa_names"] == [f["properties"]["NAME"] for f in features]
    assert set(coverage["repaired_names"]) == expected_repairs
    assert set(coverage["gea_names"]) == expected_geas
    assert coverage["gea_source_sha256"] == GEA_SHA
    assert coverage["statement"] == STATEMENT
    if rid == "outer-islands-borderland":
        staged = load(RECEIPTS / f"{rid}-groundfish-exclusions.geojson")
        assert staged["region_id"] == rid
        assert staged["features"] == selected
        assert json.dumps(staged["features"], separators=(",", ":")) == json.dumps(selected, separators=(",", ":"))
        assert staged["source_sha256"] == GEA_SHA
        for key in ("source_url", "note"):
            assert staged[key] == gea[key]
        assert staged["derived_from"] == {"path": GEA_PATH, "sha256": hashlib.sha256((ROOT / GEA_PATH).read_bytes()).hexdigest()}


def test_bolsa_invalid_components_need_explicit_repair():
    # Offline negative control: preserve the real feature identity, substitute
    # the nested-component topology of the raw CDFW response, not its coordinates.
    rid = "san-pedro-orange-county"
    region = load(ROOT / "regions" / rid / "region.json")
    snapshot = load(RECEIPTS / f"{rid}-protected-areas.geojson")
    feature = next(f for f in snapshot["features"] if f["properties"]["NAME"] == BOLSA)
    x, y, _, _ = shape(feature["geometry"]).bounds
    outer = Polygon([(x, y), (x + .01, y), (x + .01, y + .01), (x, y + .01)])
    inner = Polygon([(x + .002, y + .002), (x + .004, y + .002), (x + .004, y + .004), (x + .002, y + .004)])
    feature["geometry"] = mapping(MultiPolygon([outer, inner]))
    feature["properties"].pop("geometry_repair")
    with pytest.raises(ValueError, match="polygon invalid"):
        validate_response(deepcopy(snapshot), region["mpa"]["bounds"], 4)

"""A declared non-WGS84 or malformed collection CRS cannot certify DS582 coverage."""
from __future__ import annotations

import copy
from urllib.parse import urlencode

import pytest

from skippercast.platform.protected_areas import (
    CDFW_SERVICE, QUERY_SEMANTICS, SnapshotCoverage, assess_snapshot_binding,
)

OK = SnapshotCoverage(True, "Recorded DS582 query envelope contains region.mpa.bounds; "
                            "freshness and legal clearance remain separate")
CRS_REFUSAL = SnapshotCoverage(False, "Unsupported or malformed protected-area snapshot CRS")
SENTINEL = "SENTINEL-PAYLOAD-7f3a"


def _url(**changes):
    params = {**QUERY_SEMANTICS, "geometry": "-122,34,-120,36", **changes}
    return CDFW_SERVICE + "/query?" + urlencode(params)


def _inputs(**snapshot_changes):
    region = {"id": "synthetic-coast", "source_bindings": {"protected-areas": ["cdfw-mpas"]},
              "mpa": {"bounds": [-121.5, 34.5, -120.5, 35.5], "minimum_features": 1}}
    sources = {"cdfw-mpas": {"review_status": "approved", "needs": ["protected-areas"],
                             "service_url": CDFW_SERVICE}}
    ring = [[-121.0, 35.0], [-120.9, 35.0], [-120.9, 35.1], [-121.0, 35.0]]
    snapshot = {"type": "FeatureCollection", "source_url": _url(),
                "features": [{"type": "Feature", "properties": {},
                              "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    snapshot.update(snapshot_changes)
    return region, snapshot, sources


def _assess(region, snapshot, sources):
    before = copy.deepcopy((region, snapshot, sources))
    result = assess_snapshot_binding(region, snapshot, sources)
    assert (region, snapshot, sources) == before
    return result


def _named(name):
    return {"type": "name", "properties": {"name": name}}


def test_projected_crs_cannot_certify_degree_coverage():
    assert _assess(*_inputs()) == OK
    assert _assess(*_inputs(crs=_named("EPSG:3857"))) == CRS_REFUSAL


@pytest.mark.parametrize("name", ["EPSG:4326", "urn:ogc:def:crs:EPSG::4326",
                                  "OGC:CRS84", "urn:ogc:def:crs:OGC:1.3:CRS84"])
def test_recognized_wgs84_names_preserve_result(name):
    region, snapshot, sources = _inputs(crs=_named(name))
    features, url = copy.deepcopy(snapshot["features"]), snapshot["source_url"]
    assert _assess(region, snapshot, sources) == _assess(*_inputs()) == OK
    assert snapshot["features"] == features and snapshot["source_url"] == url


@pytest.mark.parametrize("crs", [
    None, False, 0, "", "EPSG:4326", [], ["EPSG:4326"], {},
    {"properties": {"name": "EPSG:4326"}},
    {"type": "link", "properties": {"name": "EPSG:4326"}},
    {"type": "link", "properties": {"href": "http://example.invalid/crs", "type": "proj4"}},
    {"type": "name"}, {"type": "name", "properties": None},
    {"type": "name", "properties": "EPSG:4326"}, {"type": "name", "properties": {}},
    _named(None), _named(4326), _named(""), _named(" "), _named("epsg:4326"),
    _named("EPSG:4326 "), _named("EPSG:43260"), _named("EPSG:3857"),
    _named(["EPSG:4326"]), _named({"EPSG:4326": 1}),
])
def test_malformed_present_crs_fails_closed(crs):
    assert _assess(*_inputs()) == OK
    assert _assess(*_inputs(crs=crs)) == CRS_REFUSAL


def test_request_wgs84_does_not_override_response_crs():
    region, snapshot, sources = _inputs(crs=_named("EPSG:3857"))
    assert "inSR=4326" in snapshot["source_url"] and "outSR=4326" in snapshot["source_url"]
    assert _assess(region, snapshot, sources) == CRS_REFUSAL
    assert _assess(*_inputs(crs=_named("EPSG:3857"), source_url=_url(geometry="-180,-90,180,90"))) \
        == CRS_REFUSAL


@pytest.mark.parametrize("crs", [None, _named("EPSG:4326")])
@pytest.mark.parametrize("changes, reason", [
    ({"region_id": "other"}, "Protected-area snapshot belongs to another region"),
    ({"exceededTransferLimit": True}, "Truncated or ambiguous protected-area response"),
    ({"features": []}, "Insufficient protected-area boundary features"),
    ({"features": [{"type": "Feature", "geometry": None}]}, "Malformed protected-area boundary feature"),
    ({"source_url": _url(where="NAME='x'")}, "Missing or unsupported protected-area envelope query semantics"),
    ({"source_url": _url(resultOffset="0")},
     "Filtered, paginated or unsupported protected-area query parameters"),
    ({"source_url": _url() + "&f=geojson"}, "Ambiguous duplicate protected-area query parameters"),
    ({"source_url": _url(geometry="-121,35,-120.9,35.1")},
     "Recorded protected-area query envelope does not contain region.mpa.bounds"),
])
def test_legacy_binding_refusals_remain_conservative(crs, changes, reason):
    extra = {} if crs is None else {"crs": crs}
    assert _assess(*_inputs(**extra, **changes)) == SnapshotCoverage(False, reason)


@pytest.mark.parametrize("crs", [_named(SENTINEL), _named("EPSG:3857 " + SENTINEL),
                                 {"type": SENTINEL, "properties": {"name": SENTINEL}}])
def test_assessor_is_pure_and_payload_free(crs):
    result = _assess(*_inputs(crs=crs))
    assert result == CRS_REFUSAL and SENTINEL not in result.reason
    assert _assess(*_inputs(crs=_named("OGC:CRS84"))) == OK

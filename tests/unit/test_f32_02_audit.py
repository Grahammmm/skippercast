"""F32-02: matching counts and snapshot hashes do not prove usable geometry."""
import hashlib
import json

import pytest

from research.scripts import refresh_enc_hazards as enc
from research.scripts import report_enc_hazard_coverage as reporter

pytestmark = pytest.mark.gis

# Invented integer-degree envelope; none of these are chart or user records.
SCOPE = {"id": "synthetic", "region_id": "synthetic", "bounds": [-123, 36, -121, 38]}
RUN = "synthetic:1"
CROSSING = {"type": "LineString", "coordinates": [[-124, 37], [-120, 37]]}
SHELL = [[-124, 35], [-120, 35], [-120, 39], [-124, 39], [-124, 35]]
HOLE = [[-123.5, 35.5], [-120.5, 35.5], [-120.5, 38.5], [-123.5, 38.5], [-123.5, 35.5]]
BAD_GEOMETRIES = [
    pytest.param({"type": "Point"}, id="type-only"),
    pytest.param({"type": "Point", "coordinates": [float("nan"), 37]}, id="nan"),
    pytest.param({"type": "Point", "coordinates": [-122, 37, float("inf")]}, id="infinite-z"),
    pytest.param({"type": "Point", "coordinates": ["-122", 37]}, id="string-ordinate"),
    pytest.param({"type": "LineString", "coordinates": []}, id="empty-line"),
    pytest.param({"type": "LineString", "coordinates": [[-122, 37]] * 2}, id="collapsed-line"),
    pytest.param({"type": "Polygon", "coordinates": [SHELL[:-1]]}, id="unclosed-ring"),
    pytest.param({"type": "Polygon", "coordinates": [[[-124, 35], [-120, 39],
                  [-123, 39], [-121, 35], [-124, 35]]]}, id="self-crossing-ring"),
    pytest.param({"type": "MultiPolygon", "coordinates": [[SHELL], []]}, id="empty-polygon-member"),
    pytest.param({"type": "MultiPolygon", "coordinates": [[SHELL], [SHELL]]}, id="overlapping-members"),
    pytest.param({"type": "Point", "coordinates": [-124, 37]}, id="outside-point"),
    pytest.param({"type": "LineString", "coordinates": [[-124, 37], [-122, 40]]}, id="bbox-only-overlap"),
    pytest.param({"type": "Polygon", "coordinates": [SHELL, HOLE]}, id="envelope-in-hole"),
]


@pytest.fixture
def run_refresh(tmp_path, monkeypatch):
    """Drive the CLI and real query path, substituting only local provider replies."""
    catalog = tmp_path / "research/catalog"
    catalog.mkdir(parents=True)
    (catalog / "noaa-enc-hazard-scopes.json").write_text(json.dumps({
        "schema_version": 1, "source_url": enc.BASE, "scopes": [SCOPE],
    }))
    output = tmp_path / "var/synthetic.geojson"
    monkeypatch.setattr(enc, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["refresh_enc_hazards.py", "--scope", SCOPE["id"],
                                    "--output", str(output), "--invocation", RUN])

    def run(*geometries, outage=False):
        def fetch(url):
            service, endpoint = url.removeprefix(enc.BASE + "/").split("/MapServer", 1)
            if endpoint == "?f=pjson":
                prefix = {"enc_harbour": "Harbor", "enc_approach": "Approach",
                          "enc_coastal": "Coastal"}[service]
                data = {"layers": [{"name": f"{prefix}.{layer}", "id": i}
                                   for i, layer in enumerate(enc.LAYERS)]}
            else:
                if outage and service == "enc_harbour" and endpoint.startswith("/0/query?"):
                    raise enc.EncUpstreamUnavailable("synthetic exhausted retry budget")
                features = ([{"type": "Feature", "geometry": g, "properties": {}} for g in geometries]
                            if service == "enc_harbour" and endpoint.startswith("/1/query?") else [])
                data = ({"count": len(features)} if "returnCountOnly=true" in endpoint else
                        {"type": "FeatureCollection", "features": features})
            return data, hashlib.sha256(json.dumps(data).encode()).hexdigest()

        monkeypatch.setattr(enc, "fetch_json", fetch)
        enc.main()

    return output, run


@pytest.mark.parametrize("geometry", BAD_GEOMETRIES)
def test_matching_provider_counts_do_not_make_invalid_geometry_successful(run_refresh, geometry, capsys):
    output, run = run_refresh
    # A concurrent outage cannot override the geometry validation failure.
    with pytest.raises(ValueError, match="ENC danger geometry"):
        run(geometry, outage=True)
    assert not output.exists()
    assert not output.with_suffix(".unavailable.json").exists()
    assert "::warning" not in capsys.readouterr().out
    lines, unhealthy = reporter.report_bound(output.parent, (SCOPE["id"],), invocation=RUN)
    assert unhealthy == [SCOPE["id"]]
    assert "status is failed" in lines[1]


@pytest.mark.parametrize("geometry", BAD_GEOMETRIES)
def test_bound_readback_rejects_invalid_geometry_even_with_matching_digest(run_refresh, geometry):
    output, run = run_refresh
    run(CROSSING)
    snapshot = json.loads(output.read_bytes())
    snapshot["features"][0]["geometry"] = geometry
    raw = json.dumps(snapshot).encode()
    output.write_bytes(raw)
    status_path = output.with_suffix(enc.RUN_STATUS_SUFFIX)
    status = json.loads(status_path.read_bytes())
    status["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
    status_path.write_text(json.dumps(status))

    lines, unhealthy = reporter.report_bound(output.parent, (SCOPE["id"],), invocation=RUN)
    assert unhealthy == [SCOPE["id"]]
    assert "complete layer queries" not in lines[1]
    assert "upstream_unavailable" not in lines[1]


def test_valid_crossing_geometries_and_zero_count_layers_report_complete(run_refresh):
    output, run = run_refresh
    run(CROSSING, {"type": "Point", "coordinates": [-123, 37, 0]},
        {"type": "Polygon", "coordinates": [SHELL]},
        {"type": "MultiPolygon", "coordinates": [[SHELL], [[[-118, 36], [-117, 36],
                                                             [-117, 38], [-118, 36]]]]})
    counts = [receipt["count"] for receipt in json.loads(output.read_bytes())["query_receipts"]]
    assert sorted(counts) == [0] * 17 + [4]
    lines, unhealthy = reporter.report_bound(output.parent, (SCOPE["id"],), invocation=RUN)
    assert unhealthy == []
    assert "4 charted features across 18 complete layer queries" in lines[1]

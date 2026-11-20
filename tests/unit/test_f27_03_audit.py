"""Offline controls for the Estero spatial VDatum request boundary."""

import io
import json
import sys
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def spatial_run(tmp_path, monkeypatch):
    from pyproj import network

    from research.scripts import audit_estero_vdatum_spatial as spatial

    network_was_enabled = network.is_network_enabled()
    network.set_network_enabled(False)
    blocks_path = tmp_path / "blocks.geojson"
    private_path = tmp_path / "samples.json"
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["audit_estero_vdatum_spatial.py",
                                     "--blocks", str(blocks_path),
                                     "--private-output", str(private_path),
                                     "--output", str(report_path)])

    def run(crs):
        # Invented UTM envelope, not sourced from the Estero block archive.
        ring = [[500_000, 5_000_000], [503_000, 5_000_000], [503_000, 5_002_100],
                [500_000, 5_002_100], [500_000, 5_000_000]]
        feature = {"type": "Feature", "properties": {"fishing_target": False},
                   "geometry": {"type": "Polygon", "coordinates": [ring]}}
        blocks = {"type": "FeatureCollection", "features": [feature] * 60}
        if crs is not None:
            blocks["crs"] = crs
        blocks_path.write_text(json.dumps(blocks))
        spatial.main()

    try:
        yield spatial, run, private_path, report_path
    finally:
        network.set_network_enabled(network_was_enabled)


@pytest.mark.parametrize("crs", [None, "EPSG:26910"], ids=["missing", "wrong"])
def test_rejects_undeclared_or_wrong_block_crs_before_request(spatial_run, monkeypatch, crs):
    spatial, run, private_path, report_path = spatial_run
    transport = Mock(side_effect=AssertionError("invalid block CRS reached the transport"))
    monkeypatch.setattr(spatial, "urlopen", transport)

    with pytest.raises(ValueError, match=r"CRS.*EPSG:32610"):
        run(crs)

    transport.assert_not_called()
    assert not private_path.exists()
    assert not report_path.exists()


def test_requests_reference_wgs84_lattice_with_separate_noaa_frame(spatial_run, monkeypatch):
    from pyproj import Transformer

    spatial, run, _, _ = spatial_run

    class Response(io.StringIO):
        status = 200
        headers = {"Content-Type": "application/json"}

    def reply(*_args, **_kwargs):
        return Response(json.dumps({
            "s_h_frame": "NAD83_2011", "s_v_frame": "NAVD88", "t_v_frame": "MLLW",
            "region": "WESTCOAST", "t_z": -0.7, "uncertainty": 0.1,
        }))

    transport = Mock(side_effect=reply)
    monkeypatch.setattr(spatial, "urlopen", transport)
    run("EPSG:32610")

    reference = Transformer.from_crs(32610, 4326, always_xy=True)
    expected = []
    for northing in range(5_000_000, 5_002_101, 700):
        for easting in range(500_000, 503_001, 500):
            lon, lat = reference.transform(easting, northing)
            expected.append((f"{lon:.8f}", f"{lat:.8f}"))
    actual = []
    for call in transport.call_args_list:
        params = parse_qs(urlsplit(call.args[0].full_url).query)
        assert params["s_h_frame"] == ["NAD83_2011"]
        assert "epoch_in" not in params
        actual.append((params["s_x"][0], params["s_y"][0]))
    # The old NAD83 UTM inverse differs even at request precision on this grid.
    assert sorted(actual) == sorted(expected)

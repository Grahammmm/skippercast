"""Offline CLI fixtures for the R5c mapping zone and honest detail labels."""
import hashlib
import json
import subprocess
import sys

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis


@pytest.fixture
def region_inputs(tmp_path):
    np = pytest.importorskip("numpy")
    rio = pytest.importorskip("rasterio")
    shapely = pytest.importorskip("shapely")
    geom = pytest.importorskip("shapely.geometry")
    project = pytest.importorskip("pyproj").Transformer.from_crs(3310, 4326, always_xy=True).transform

    x0, y0 = 0, -200_000

    def position(x, y):
        return geom.Point(*project(x0 + x, y0 + y))

    def write_raster(name, data, *, cell=10, x=200, y=-500, nodata=0):
        data = np.asarray(data)
        with rio.open(tmp_path / name, "w", driver="GTiff", count=1, crs="EPSG:3310",
                      width=data.shape[1], height=data.shape[0], dtype=data.dtype, nodata=nodata,
                      transform=rio.Affine(cell, 0, x0 + x, 0, -cell, y0 + y)) as ds:
            ds.write(data, 1)

    def write_json(name, doc):
        (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")

    region = "synthetic-coast"
    write_json("region.json", {"id": region, "bounds": [*project(-250, y0 - 3500), *project(3600, y0 + 100)]})
    # The coarse contour lies at x=1500; water extends past the buffer and has an island.
    write_raster("coarse.tif", np.tile(np.float32([20, -10, -30, -91.44, -95, -110, -130, -150]), (8, 1)),
                 x=-500, y=0, cell=500, nodata=-9999)
    water = geom.box(0, y0 - 4000, 3500, y0 + 500).difference(geom.box(1200, y0 - 1400, 1400, y0 - 1200))
    write_json("water.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": geom.mapping(
            shapely.transform(water, project, interleaved=False))}
    ]})
    # Two rows: nominal 20 m (inclusive) and 30 m. Contributor zero in the
    # center of the bottom row is a hole, not another kind of valid support.
    win = np.tile(np.uint16([1, 1, 1, 2, 3, 4, 5, 6]), (3, 1))
    win[1, 1] = 0
    depths = np.vstack([np.full(8, -20), np.full(8, -30), np.full(8, -30)]).astype("float32")
    depths[1, 1] = -9999
    classes = np.tile(np.uint8([3, 1, 2, 3, 3, 3, 3, 0]), (3, 1))
    classes[1, 1] = 0
    write_raster("elevation.tif", depths, nodata=-9999)
    write_raster("contributor.tif", win)
    write_raster("support_class.tif", classes)
    surveys = [(1, "fine", 1, "measured"), (2, "two", 2, "measured"), (3, "five", 5, "measured"),
               (4, "compiled", 8, "compiled"), (5, "filled", 1, "interpolated"), (6, "uncertified", 1, "measured")]
    write_json("manifest.json", {"segment": region, "sources": [
        dict(code=code, id=ident, resolution_m=spacing) for code, ident, spacing, _ in surveys
    ]})
    selection = {"region": region, "sources": [
        dict(id=ident, name=f"Synthetic {ident}", rights_class="public", label=label, date="2025-10-07")
        for _, ident, _, label in surveys
    ]}
    write_json("selection.json", selection)

    def run(out="out", *, support=True, ok=True):
        command = [sys.executable, str(ROOT / "scripts" / "build_survey_zone.py"),
                   "--region", "region.json", "--coarse", "coarse.tif", "--water", "water.geojson",
                   "--mosaic", ".", "--selection", "selection.json", "--output", out,
                   "--coarse-source", "statewide-fixture", "--coarse-date", "2024-01-03"]
        if support:
            command.extend(["--support", "support_class.tif"])
        result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
        if not ok:
            return result
        assert result.returncode == 0, result.stderr
        return tuple((tmp_path / out / f"{kind}.geojson").read_bytes() for kind in ("zone", "detail"))

    return run, position, geom, selection, write_json


def _at(doc, position, geom):
    return [feature["properties"] for feature in json.loads(doc)["features"]
            if geom.shape(feature["geometry"]).covers(position)]


def test_zone_and_hatch_keep_land_and_offshore_out_and_keep_survey_holes(region_inputs):
    run, point, geom, _, _ = region_inputs
    zone, detail = run()
    zone_geom = geom.shape(json.loads(zone)["features"][0]["geometry"])
    assert zone_geom.is_valid
    assert zone_geom.covers(point(10, -1500))  # shoreward water
    assert zone_geom.covers(point(2490, -1500))  # 1 km buffer, beyond the 300 ft contour
    assert not zone_geom.covers(point(2510, -1500))
    assert _at(detail, point(2490, -1500), geom) == [{"tier": "none", "sources": [], "date": None}]
    for x, y in [(2600, -1500), (-50, -1500), (1300, -1300)]:
        assert not zone_geom.covers(point(x, y))  # out-of-zone water, mainland, island hole
        assert not _at(detail, point(x, y), geom)
    assert _at(detail, point(215, -515), geom)[0]["tier"] == "none"
    assert _at(detail, point(215, -525), geom)[0]["tier"] == "estimated"
    assert json.loads(zone)["features"][0]["properties"] == {
        "sources": ["statewide-fixture"], "date": "2024-01-03", "limit_ft": 300, "buffer_m": 1000,
    }


def test_detail_requires_cell_evidence_and_uses_shallow_band(region_inputs):
    run, point, geom, _, _ = region_inputs
    _, detail = run()
    shallow = [_at(detail, point(205 + 10 * i, -505), geom) for i in range(8)]
    assert [p[0]["tier"] for p in shallow] == ["1m-measured"] + ["estimated"] * 7
    assert all(len(features) == 1 for features in shallow)
    assert shallow[3][0] == {"tier": "estimated", "grid_m": 2, "source": "Synthetic two",
                             "date": "2025-10-07", "sources": ["two"]}
    assert shallow[5][0]["grid_tier"] == "4-16m-compiled"
    assert [_at(detail, point(x, -525), geom)[0]["tier"] for x in (205, 235, 245, 255)] == [
        "1m-measured", "2m", "5m", "estimated",
    ]
    _, no_support = run("no-support", support=False)
    tiers = {feature["properties"]["tier"] for feature in json.loads(no_support)["features"]}
    assert tiers == {"none", "estimated"}


def test_coarse_contour_in_neighboring_region_still_buffers_into_region(region_inputs):
    run, point, geom, _, write_json = region_inputs
    # This region begins offshore of the 300 ft contour. Clipping the
    # band before buffering would leave its zone and hatch entirely empty.
    west, south = point(1750, -2450).coords[0]
    east, north = point(2900, -500).coords[0]
    write_json("region.json", {"id": "synthetic-coast", "bounds": [west, south, east, north]})
    zone, detail = run()
    assert _at(zone, point(2000, -1500), geom)
    assert _at(detail, point(2000, -1500), geom)[0]["tier"] == "none"
    assert not _at(detail, point(1650, -1500), geom)  # outside the region
    assert not _at(detail, point(2600, -1500), geom)  # beyond the halo


def test_zone_and_detail_are_byte_stable(region_inputs):
    run, _, _, selection, write_json = region_inputs
    first = [hashlib.sha256(data).hexdigest() for data in run("first")]
    selection["sources"].reverse()
    write_json("selection.json", selection)
    second = [hashlib.sha256(data).hexdigest() for data in run("second")]
    print(f"SHA-256 (zone, detail): {first} == {second}")
    assert first == second


def test_unapproved_mosaic_contributor_is_refused(region_inputs, tmp_path):
    run, _, _, selection, write_json = region_inputs
    selection["sources"][0]["rights_class"] = "private"
    write_json("selection.json", selection)
    result = run(ok=False)
    assert result.returncode != 0
    assert "no public selection row" in result.stderr
    assert not (tmp_path / "out").exists()

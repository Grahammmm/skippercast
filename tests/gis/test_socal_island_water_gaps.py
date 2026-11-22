"""Synthetic fixtures at the island gap report's file-to-area boundary."""

import json

from pyproj import Transformer
import pytest
from shapely.geometry import MultiPolygon, Polygon, box, mapping

from scripts.relief.socal_island_water_gaps import main, report_water_gaps

NORTH = "channel-islands-north"
OUTER = "outer-islands-borderland"


def fixture(root, region, name, geometry):
    path = root / region / f"{name}.geojson"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(mapping(geometry)), encoding="utf-8")


def rectangle_m2(west, south, east, north):
    """Independent four-corner area oracle for these small rectangles."""
    xy = Transformer.from_crs(4326, 3310, always_xy=True).itransform(
        [(west, south), (east, south), (east, north), (west, north)]
    )
    return Polygon(list(xy)).area


def test_island_hole_stays_land_even_under_a_single_crossing_support_patch(tmp_path, monkeypatch, capsys):
    # A patch crosses the hole but leaves uncovered water; counting land in
    # either the water footprint or the support intersection changes the answer.
    shell = box(-120.02, 33.98, -119.98, 34.02)
    hole = box(-120.01, 33.99, -119.99, 34.01)
    patch = box(-120.02, 33.98, -120.0, 34.02)
    fixture(tmp_path, NORTH, "water", Polygon(shell.exterior.coords, [hole.exterior.coords]))
    fixture(tmp_path, NORTH, "usable-support", patch)
    monkeypatch.setattr("sys.argv", ["socal_island_water_gaps.py", str(tmp_path)])
    main()
    report = json.loads(capsys.readouterr().out)
    row = report["windows"][NORTH]
    water_m2 = rectangle_m2(*shell.bounds) - rectangle_m2(*hole.bounds)
    right_water_m2 = rectangle_m2(-120.0, 33.98, -119.98, 34.02) - rectangle_m2(-120.0, 33.99, -119.99, 34.01)
    assert report["area_epsg"] == 3310
    assert row["water_m2"] == pytest.approx(water_m2, rel=1e-6)
    assert row["unsupported_water_m2"] == pytest.approx(right_water_m2, rel=1e-6)
    assert 0 < row["unsupported_water_m2"] < row["water_m2"]


def test_areas_are_clipped_and_reported_separately_for_the_two_windows(tmp_path):
    # Each fixture crosses its region's west edge; reusing the other window,
    # measuring the whole fixture, or summing the two windows gives a wrong area.
    north_water = box(-120.62, 34.0, -120.58, 34.02)
    outer_water = box(-119.72, 33.0, -119.68, 33.03)
    fixture(tmp_path, NORTH, "water", north_water)
    fixture(tmp_path, NORTH, "usable-support", north_water)
    fixture(tmp_path, OUTER, "water", MultiPolygon([outer_water, north_water]))
    fixture(tmp_path, OUTER, "usable-support", north_water)
    report = report_water_gaps(tmp_path)
    assert report == {
        "area_epsg": 3310,
        "windows": {
            NORTH: {
                "water_m2": pytest.approx(rectangle_m2(-120.6, 34.0, -120.58, 34.02), rel=1e-6),
                "unsupported_water_m2": 0,
            },
            OUTER: {
                "water_m2": pytest.approx(rectangle_m2(-119.7, 33.0, -119.68, 33.03), rel=1e-6),
                "unsupported_water_m2": pytest.approx(rectangle_m2(-119.7, 33.0, -119.68, 33.03), rel=1e-6),
            },
        },
    }


def test_missing_fixtures_do_not_invent_water_or_gaps(tmp_path):
    # Support cannot manufacture water evidence, and missing support is not the
    # same as measured support with zero overlap (the previous test's outer row).
    north_water = box(-120.02, 33.98, -119.98, 34.02)
    fixture(tmp_path, NORTH, "water", north_water)
    fixture(tmp_path, OUTER, "usable-support", box(-119.65, 33.0, -119.63, 33.02))
    rows = report_water_gaps(tmp_path)["windows"]
    assert rows[NORTH] == {
        "water_m2": pytest.approx(rectangle_m2(*north_water.bounds), rel=1e-6),
        "unsupported_water_m2": None,
    }
    assert rows[OUTER] == {"water_m2": None, "unsupported_water_m2": None}


@pytest.mark.parametrize(
    ("name", "geometry", "error"),
    [
        ("water", Polygon([(-120, 34), (-119.9, 34.1), (-120, 34.1), (-119.9, 34)]), "valid 2D polygon"),
        ("usable-support", box(1000, 1000, 1001, 1001), "WGS84 longitude/latitude"),
    ],
)
def test_present_invalid_evidence_is_rejected(tmp_path, name, geometry, error):
    # No silent repair of self-crossing water and no misreading a projected
    # support file as disjoint WGS84 evidence.
    fixture(tmp_path, NORTH, "water", box(-120.02, 33.98, -119.98, 34.02))
    fixture(tmp_path, NORTH, name, geometry)
    with pytest.raises(ValueError, match=error):
        report_water_gaps(tmp_path)

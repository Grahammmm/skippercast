"""Synthetic geometry contracts for the regional water builder."""

import json
import math

import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from scripts.build_survey_zone import _water
from skippercast.relief.water import _displacement, ocean_polygon, to_geojson

FRAME = (-120.025, 37.98, -119.975, 38.02)
TO_METRES = Transformer.from_crs(4326, 3310, always_xy=True)
TO_DEGREES = Transformer.from_crs(3310, 4326, always_xy=True)
Y = TO_METRES.transform(-120, 38)[1]


def _line(*xy):
    return LineString([TO_DEGREES.transform(x, Y + y) for x, y in xy])


def _point(x, y):
    return Point(TO_DEGREES.transform(x, Y + y))


def _ocean(*lines, frame=FRAME, connect_m=250):
    return ocean_polygon([(line, 18) for line in lines], frame, close_m=18, connect_m=connect_m)


def test_c1_west_ocean_with_island(tmp_path):
    """C1: Keep all and only the west component, including its island hole."""
    coast = _line((0, -4000), (0, 4000))
    island = _line((-800, -100), (-600, -100), (-600, 100), (-800, 100), (-800, -100))
    # A largest-area fill or a union of both sides would include this inland point.
    water, report = ocean_polygon([(coast, 18), (island, 4)],
                                  (-120.025004, 37.979998, -119.974993, 38.020014),
                                  close_m=18, connect_m=250)
    assert isinstance(water, Polygon)
    assert water.is_valid
    assert len(water.interiors) == 1
    assert [water.contains(_point(x, 0)) for x in (-1000, -700, -500, 500)] == [True, False, True, False]
    assert water.bounds[0:2] == (-120.025, 37.98)
    assert water.bounds[3] == 38.02001
    assert box(-120.025, 37.98, -119.975, 38.02001).covers(water)
    assert report["cut_arcs"] == []
    assert len(report["components_dropped"]) == 2  # inland and island interior
    island_inside, mainland = report["components_dropped"]
    assert island_inside["area_m2_epsg3310"] == (200 - 2 * 18) ** 2
    assert box(*island_inside["bounds_wgs84"]).contains(_point(-700, 0))
    assert box(*mainland["bounds_wgs84"]).contains(_point(500, 0))
    assert report["unlisted_beyond_bound"] == []
    path = tmp_path / "island-water.geojson"
    path.write_text(json.dumps(to_geojson(water, "synthetic-coast"), allow_nan=False), encoding="utf-8")
    assert _water(path).equals(shapely.transform(water, TO_METRES.transform, interleaved=False))


@pytest.mark.parametrize("reaches_east", [
    pytest.param(True, id="C1: cut and list narrow river leading east"),
    pytest.param(False, id="C1: retain an otherwise identical dead-end inlet"),
])
def test_c1_river_cut_only_for_east_connection(reaches_east):
    """C1: Connectivity cutting must not erase an inland-ending inlet."""
    lower = _line((0, -4000), (0, -650), (550, -650), (550, -55), (4000, -55))
    upper = _line((0, 4000), (0, 650), (550, 650), (550, 55), (4000, 55))
    lines = [lower, upper]
    if not reaches_east:
        lines.append(_line((1550, -55), (1550, 55)))
    water, report = _ocean(*lines)
    assert [water.contains(_point(x, 0)) for x in (-500, 250, 1100)] == [True, True, not reaches_east]
    assert water.intersection(LineString([(FRAME[2], FRAME[1]), (FRAME[2], FRAME[3])])).is_empty
    if reaches_east:
        assert len(report["components_dropped"]) == 3
        assert len(report["cut_arcs"]) == 1
        arc, = report["cut_arcs"]
        assert set(arc) == {"from_lon_lat", "to_lon_lat", "mid_lon_lat", "length_m"}
        x, y = TO_METRES.transform(*arc["mid_lon_lat"])
        assert 300 < x < 650 and abs(y - Y) < 4
        assert arc["length_m"] > 74  # crosses the 110 m river's 74 m clearance core
        assert report["max_displacement_m"] > report["displacement_bound_m"]
    else:
        assert report["cut_arcs"] == []
        assert len(report["components_dropped"]) == 3
    assert report["unlisted_beyond_bound"] == []


@pytest.mark.parametrize("gap,opens", [
    pytest.param(35, False, id="C2: close the 35 m break without exceeding 2r"),
    pytest.param(50, True, id="C2: a break wider than 2r stays open"),
])
def test_c2_opening_gap_threshold(gap, opens):
    """C2: Opening (not snapping) preserves the wider break as a water passage."""
    lower = _line((0, -4000), (0, -gap / 2))
    upper = _line((0, gap / 2), (0, 4000))
    # Back wall separates the bay from the inland frame edge. No east cut can
    # mask whether the shoreline opening itself closed the break.
    back = _line((650, -4000), (650, 4000))
    water, report = _ocean(lower, upper, back)
    assert [water.contains(_point(x, 0)) for x in (-100, 100, 900)] == [True, opens, False]
    assert len(report["components_dropped"]) == (1 if opens else 2)
    maximum = report["max_displacement_m"]
    assert type(maximum) is float
    assert maximum == round(maximum, 2)
    assert (0 if opens else 18) < maximum <= 36
    assert report.keys() == {"cut_arcs", "components_dropped", "max_displacement_m",
                             "displacement_bound_m", "unlisted_beyond_bound"}
    assert report["displacement_bound_m"] == 36
    assert report["cut_arcs"] == report["unlisted_beyond_bound"] == []


@pytest.mark.parametrize("offset,cut_x,flagged", [
    pytest.param(40, None, True, id="C2: list uncut samples 40 m from the line"),
    pytest.param(36.5, None, False, id="C2: allow the half-metre tolerance"),
    pytest.param(40, 59, False, id="C2: exempt samples within radius plus one metre of a listed cut"),
    pytest.param(40, 59.01, True, id="C2: do not exempt samples beyond the cut margin"),
])
def test_c2_displacement_sampler(offset, cut_x, flagged):
    """C2: Thresholds gate individual 2 m samples, not the reported maximum."""
    shore = LineString([(offset, Y + 5), (offset, Y)])
    source = LineString([(0, Y - 10), (0, Y + 10)])
    cuts = [] if cut_x is None else [LineString([(cut_x, Y - 10), (cut_x, Y + 10)])]
    expected = sorted([round(lon, 5), round(lat, 5)]
                      for lon, lat in (TO_DEGREES.transform(offset, Y + dy) for dy in (0, 1, 3, 5)))
    assert _displacement(shore, source, cuts, 18, TO_DEGREES) == {
        "max_displacement_m": offset,
        "displacement_bound_m": 36,
        "unlisted_beyond_bound": expected if flagged else [],
    }


@pytest.mark.parametrize("frame,coast,radii,error", [
    pytest.param(FRAME, [(0, -4000), (0, 4000)], (18, 17), "finite radii", id="C1: refuse inconsistent radii"),
    pytest.param(FRAME, [(0, -4000), (0, 4000)], (19, 250), "maximum stated", id="C1: refuse unstated opening radius"),
    pytest.param((0, 0, -1, 1), [(0, -4000), (0, 4000)], (18, 250), "ordered WGS84", id="C1: refuse invalid frame"),
    pytest.param((-120, 38, -119.999999, 39), [(0, -4000), (0, 4000)], (18, 250), "vanishes", id="C1: refuse collapsed frame"),
    pytest.param(FRAME, [(0, 0), (0, 0)], (18, 250), "nonempty 2D", id="C1: refuse degenerate shoreline"),
    pytest.param(FRAME, [(-4000, 0), (-1800, 0), (0, 4000)], (18, 250), "west-frame seed", id="C1: refuse obstructed west seed"),
    pytest.param(FRAME, [(-4000, 100), (4000, 100)], (18, 250), "west-frame seed", id="C1: refuse missing west cut core"),
    pytest.param(FRAME, [(-4000, -4000), (-3000, -3000)], (18, 250), "still reaches the east", id="C1: refuse unresolved east leak"),
])
def test_c1_refuses_without_guessing(frame, coast, radii, error):
    """C1: Fail closed rather than synthesize shoreline or guess a component."""
    with pytest.raises(ValueError, match=error) as exc:
        ocean_polygon([(_line(*coast), 18)], frame, close_m=radii[0], connect_m=radii[1])
    assert exc.type is ValueError


@pytest.mark.parametrize("multi", [
    pytest.param(False, id="C3: Polygon with an oriented hole"),
    pytest.param(True, id="C3: MultiPolygon with an oriented hole"),
])
def test_c3_to_geojson_round_trip(tmp_path, multi):
    """C3: Correct wrong winding and serve the real survey-zone loader."""
    # Deliberately reversed to detect a serializer that simply calls mapping.
    exterior = ((-120, 38), (-120, 38.02), (-119.98, 38.02), (-119.98, 38), (-120, 38))
    hole = ((-119.995, 38.005), (-119.985, 38.005), (-119.985, 38.015), (-119.995, 38.015),
            (-119.995, 38.005))
    extra = ((-120.02, 38), (-120.01, 38), (-120.01, 38.01), (-120.02, 38.01), (-120.02, 38))
    polygon = Polygon(exterior, [hole])
    geom = MultiPolygon([polygon, Polygon(extra)]) if multi else polygon
    rings = (exterior[::-1], hole[::-1])
    payload = json.dumps(to_geojson(geom, "synthetic-coast"), allow_nan=False)
    expected = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"region_id": "synthetic-coast"},
        "geometry": {"type": "MultiPolygon", "coordinates": (rings, (extra,))} if multi else
                    {"type": "Polygon", "coordinates": rings},
    }]}
    assert json.loads(payload) == json.loads(json.dumps(expected))
    path = tmp_path / "water.geojson"
    path.write_text(payload, encoding="utf-8")

    loaded = _water(path)
    assert loaded.is_valid
    assert loaded.equals(shapely.transform(geom, TO_METRES.transform, interleaved=False))


@pytest.mark.parametrize("geometry", [
    pytest.param(Point(-120, 38), id="C3: refuse non-polygon geometry"),
    pytest.param(Polygon(), id="C3: refuse empty geometry"),
    pytest.param(box(181, 38, 182, 39), id="C3: refuse out-of-range positions"),
    pytest.param(Polygon([(-120, 38), (-119, 38), (-119, math.inf)]), id="C3: refuse non-finite positions"),
    pytest.param(Polygon([(-120, 38, 1), (-119, 38, 1), (-119, 39, 1)]), id="C3: refuse non-2D positions"),
    pytest.param(Polygon([(-120, 38), (-119, 39), (-119, 38), (-120, 39)]), id="C3: refuse self-intersection"),
])
def test_c3_rejects_invalid_water(geometry):
    """C3: Do not emit a FeatureCollection with unreadable or invalid geometry."""
    with pytest.raises(ValueError) as exc:
        to_geojson(geometry, "synthetic-coast")
    assert exc.type is ValueError

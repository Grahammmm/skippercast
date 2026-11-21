"""Offline contracts for partitioning water at a supplied border."""

from hashlib import sha256
import json

import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping

from skippercast.relief.border import BorderError, clip_to_us, load_boundary, no_survey

_TO_METRES = Transformer.from_crs(4326, 3310, always_xy=True)
_TO_DEGREES = Transformer.from_crs(3310, 4326, always_xy=True)
_Y = _TO_METRES.transform(-120, 38)[1]
_TRIANGLE = Polygon([(-120, 37), (-119, 37), (-119, 38), (-120, 37)])


@pytest.mark.parametrize("boundary", [
    pytest.param(_TRIANGLE, id="C1: read Polygon and hash raw bytes"),
    pytest.param(MultiPolygon([box(-123, 37, -122, 38), _TRIANGLE]),
                 id="C1: read all MultiPolygon components and hash raw bytes"),
])
def test_c1_boundary_and_digest(tmp_path, boundary):
    """C1: Do not drop components or hash normalized JSON instead of the file."""
    path = tmp_path / "boundary.geojson"
    data = (json.dumps(mapping(boundary), indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    assert load_boundary(path) == (boundary, sha256(data).hexdigest())
    assert path.read_bytes() == data
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("boundary", [
    pytest.param(box(-120, 37, -119, 38), id="C1: refuse an axis-aligned box"),
    pytest.param(MultiPolygon([box(-120, 37, -119, 38), box(-123, 37, -122, 38)]),
                 id="C1: refuse an axis-aligned MultiPolygon"),
    pytest.param(LineString([(-120, 37), (-119, 38)]), id="C1: refuse a LineString"),
    pytest.param(Polygon([(-120, 37), (-119, 38), (-120, 38), (-119, 37)]),
                 id="C1: refuse a self-crossing polygon"),
    pytest.param(Polygon(), id="C1: refuse an empty polygon"),
    pytest.param(Polygon([(181, 37), (182, 37), (182, 38)]),
                 id="C1: refuse out-of-range longitude"),
])
def test_c1_refuses_unusable_boundary(tmp_path, boundary):
    """C1: Reject unusable geometry instead of repairing or clipping with it."""
    path = tmp_path / "boundary.geojson"
    path.write_text(json.dumps(mapping(boundary)), encoding="utf-8")
    with pytest.raises(BorderError) as error:
        load_boundary(path)
    assert type(error.value) is BorderError
    assert isinstance(error.value, ValueError)


@pytest.mark.parametrize("data", [
    pytest.param("{", id="C1: refuse malformed JSON"),
    pytest.param('{"type": "Polygon"}', id="C1: refuse missing polygon coordinates"),
])
def test_c1_refuses_unreadable_geometry(tmp_path, data):
    """C1: A malformed boundary must not leak a decoder-specific error type."""
    path = tmp_path / "boundary.geojson"
    path.write_text(data, encoding="utf-8")
    with pytest.raises(BorderError) as error:
        load_boundary(path)
    assert type(error.value) is BorderError


def _metric_polygon(*xy):
    return Polygon([(x, _Y + y) for x, y in xy])


_BORDER_M = _metric_polygon((-4000, -900), (4000, 1100), (4000, 5000), (-4000, 5000))
_WATER_M = _metric_polygon((-2000, -1000), (2000, -1000), (2000, 1000), (-2000, 1000))


def _degrees(geometry):
    return shapely.transform(geometry, _TO_DEGREES.transform, interleaved=False)


def _assert_partition(water_m, expected_inside_m, expected_outside_m):
    result_m = []
    parts = clip_to_us(_degrees(water_m), _degrees(_BORDER_M))
    for part, expected_m in zip(parts, (expected_inside_m, expected_outside_m), strict=True):
        assert isinstance(part, (Polygon, MultiPolygon)) and part.is_valid
        projected = shapely.transform(part, _TO_METRES.transform, interleaved=False)
        if expected_m.is_empty:
            assert part == Polygon()
        else:
            # Compare the whole region, independent of ring order and round-trip drift.
            assert part.bounds == pytest.approx(_degrees(expected_m).bounds, abs=1e-10, rel=0)
            assert projected.symmetric_difference(expected_m).area < expected_m.area * 1e-8
        result_m.append(projected)
    assert sum(part.area for part in result_m) == pytest.approx(water_m.area, rel=0.0001)


def test_c2_partitions_along_projected_slope():
    """C2: A latitude-only split or lon/lat overlay misplaces the sloped seam."""
    # y = x/4 + 100 crosses the west/east edges at y = -400 and 600 m.
    inside = _metric_polygon((-2000, -400), (2000, 600), (2000, 1000), (-2000, 1000))
    outside = _metric_polygon((-2000, -1000), (2000, -1000), (2000, 600), (-2000, -400))
    _assert_partition(_WATER_M, inside, outside)


@pytest.mark.parametrize("water_m, is_inside", [
    pytest.param(_metric_polygon((-500, 1000), (500, 1000), (500, 2000), (-500, 2000)),
                 True, id="C2: wholly inside water leaves no remainder"),
    pytest.param(_metric_polygon((-500, -2000), (500, -2000), (500, -1000), (-500, -1000)),
                 False, id="C2: wholly outside water remains intact"),
    pytest.param(_metric_polygon((-4000, -900), (4000, 1100), (4000, -2000), (-4000, -2000)),
                 False, id="C2: water touching the border only along an edge has no inside area"),
])
def test_c2_wholly_on_one_side(water_m, is_inside):
    """C2: Do not drop full-area results or leak a shared line as inside water."""
    inside, outside = (water_m, Polygon()) if is_inside else (Polygon(), water_m)
    _assert_partition(water_m, inside, outside)


def test_c2_retains_all_areal_components():
    """C2: Keep both islands of inside water while discarding an isolated edge contact."""
    first = _metric_polygon((-500, 1000), (500, 1000), (500, 2000), (-500, 2000))
    second = _metric_polygon((-500, 3000), (500, 3000), (500, 4000), (-500, 4000))
    touching = _metric_polygon((-4000, -900), (4000, 1100), (4000, -2000), (-4000, -2000))
    _assert_partition(MultiPolygon([first, second, touching]), MultiPolygon([first, second]), touching)


def test_c3_feature_has_no_source():
    """C3: Outside water is marked no survey for this map, without a source."""
    assert no_survey(_TRIANGLE) == {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": (((-120, 37), (-119, 37), (-119, 38), (-120, 37)),)},
        "properties": {"tier": "none", "reason": "outside-us-waters"},
    }


def test_c3_empty_water_has_no_feature():
    """C3: No empty placeholder feature should appear when no outside water remains."""
    assert no_survey(Polygon()) is None

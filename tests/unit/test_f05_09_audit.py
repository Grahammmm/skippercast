"""F05-09: a geometry record carrying both a polygon and its bbox is tested against the polygon.

Contract protected: planner.geometry_in_target / plan_header containment uses the true
polygon (holes included) when a record has both `geometry` and `bbox`; a bbox that does not
match the polygon's envelope is rejected; a bbox-only record stays a valid rectangle.
Believable bug: geometry_in_target returns the bbox rectangle first, so a window wholly
inside a polygon hole passes containment. All coordinates are invented synthetic values.
"""
import pytest

box = pytest.importorskip("shapely.geometry").box  # survey stack; keeps the layout contract's top-level-import rule
pytest.importorskip("pyproj")

from skippercast.coastal.authenticated_v1.planner import geometry_in_target  # noqa: E402

pytestmark = pytest.mark.gis

CRS = "EPSG:3310"  # same CRS as the target: projection is the identity, bounds stay exact
OUTER = [(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)]
HOLE = [(300, 300), (700, 300), (700, 700), (300, 700), (300, 300)]
WINDOW_IN_HOLE = box(480, 480, 520, 520)
WINDOW_IN_SOLID = box(50, 50, 90, 90)


def _holed(with_bbox=True, bbox=(0, 0, 1000, 1000)):
    record = {"crs": CRS, "geometry": {"type": "Polygon", "coordinates": [OUTER, HOLE]}}
    if with_bbox:
        record["bbox"] = list(bbox)
    return record


def _covers(record, window):
    return geometry_in_target(record, CRS).buffer(-.1).covers(window)


def test_window_inside_polygon_hole_fails_when_bbox_also_present():
    assert not _covers(_holed(), WINDOW_IN_HOLE)  # negative control: the cited failure


def test_window_in_solid_part_passes_with_polygon_and_bbox():
    assert _covers(_holed(), WINDOW_IN_SOLID)


def test_bbox_only_rectangle_still_passes():
    record = {"crs": CRS, "bbox": [0, 0, 1000, 1000]}
    assert _covers(record, WINDOW_IN_HOLE)  # no polygon, so the rectangle is the whole role
    assert not _covers(record, box(990, 990, 1010, 1010))


def test_polygon_only_record_unchanged():
    assert not _covers(_holed(with_bbox=False), WINDOW_IN_HOLE)
    assert _covers(_holed(with_bbox=False), WINDOW_IN_SOLID)


@pytest.mark.parametrize("bbox", [
    (0, 0, 2000, 2000),  # envelope larger than the polygon
    (0, 0, 900, 1000),   # envelope smaller than the polygon
    (0, 0, 1000, float("nan")),
    (0, 0, 1000),        # wrong length
])
def test_mismatched_or_malformed_bbox_is_rejected(bbox):
    with pytest.raises(ValueError, match="bbox does not match geometry envelope"):
        geometry_in_target(_holed(bbox=bbox), CRS)

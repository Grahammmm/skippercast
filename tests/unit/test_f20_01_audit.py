"""Offline GEA admission controls for F20-01."""

import pytest

from scripts.collect_noaa_groundfish_areas import collect
from tests.unit.test_noaa_groundfish_shapes import collection, fake, feature


def ring(*points):
    # Invented geometry translated into the collector's accepted WGS84 range.
    return [[-125 + x / 8, 35 + y / 8] for x, y in (*points, points[0])]


def rectangle(left, bottom, right, top):
    return ring((left, bottom), (right, bottom), (right, top), (left, top))


def polygon(*rings):
    return {'type': 'Polygon', 'coordinates': list(rings)}


def islands(*components):
    return {'type': 'MultiPolygon', 'coordinates': list(components)}


SHELL = rectangle(0, 0, 8, 8)
HOLE = rectangle(2, 2, 6, 6)
ISLAND = rectangle(10, 1, 12, 3)
COLLINEAR = ring((0, 0), (1, 1), (2, 2))


def capture(geometry):
    return collect(getter=fake(geo=collection(dict(feature(), geometry=geometry))))


@pytest.mark.parametrize('geometry', [
    pytest.param(polygon(COLLINEAR), id='collinear'),
    pytest.param(polygon(ring((0, 0), (0, 0), (0, 0))), id='coincident'),
    pytest.param(polygon(ring((0, 0), (4, 4), (0, 4), (5, 0))), id='crossing-with-nonzero-signed-area'),
    pytest.param(polygon(SHELL, COLLINEAR), id='collapsed-hole'),
    pytest.param(polygon(SHELL, ISLAND), id='hole-outside-shell'),
    pytest.param(polygon(SHELL, HOLE, rectangle(3, 3, 4, 4)), id='nested-holes'),
    pytest.param(polygon(SHELL, HOLE, rectangle(4, 4, 7, 7)), id='overlapping-holes'),
    pytest.param(polygon(SHELL, ring((0, 4), (4, 1), (8, 4), (4, 7))), id='hole-disconnects-interior'),
    pytest.param(islands([SHELL], [COLLINEAR]), id='collapsed-component'),
    pytest.param(islands([SHELL], [HOLE]), id='nested-components'),
    pytest.param(islands([SHELL], [rectangle(3, 0, 10, 5)]), id='shared-boundary-segment'),
    pytest.param(islands([SHELL], [ring((0, 2), (4, 4), (0, 6), (-3, 4))]), id='components-cross-at-vertices'),
])
def test_invalid_topology_refuses_gea_capture(geometry):
    with pytest.raises(ValueError, match='Invalid NOAA polygon or classification'):
        capture(geometry)


@pytest.mark.parametrize('geometry', [
    pytest.param(polygon(SHELL, HOLE), id='polygon-with-hole'),
    pytest.param(polygon(SHELL, ring((0, 4), (2, 2), (2, 6))), id='hole-tangent-at-one-point'),
    pytest.param(islands([SHELL, HOLE], [ISLAND]), id='disjoint-islands'),
    pytest.param(islands([SHELL, HOLE], [rectangle(3, 3, 4, 4)]), id='island-in-hole'),
    pytest.param(islands([SHELL], [rectangle(8, 8, 10, 10)]), id='islands-touch-at-one-point'),
])
def test_valid_topology_admits_unchanged_gea_geometry(geometry):
    result = capture(geometry)
    admitted = result['features'][0]
    assert result['status'] == 'ok'
    assert admitted['geometry'] == geometry
    assert admitted['properties']['groundfish_candidate_exclusion'] is True
    assert admitted['properties']['fishing_permission'] is None

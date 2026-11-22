"""Synthetic controls for the geometry/seed relation, not the water stage."""

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box

from scripts.relief.north_water_seed_check import check_seed


@pytest.fixture
def water():
    island = [(12, 2), (14, 2), (14, 4), (12, 4)]
    bay = Polygon([(10, 0), (16, 0), (16, 6), (10, 6)], [island])
    return MultiPolygon([box(0, 0, 8, 8), bay, box(16, 6, 19, 8)])


def test_interior_identifies_supplied_seed_component_and_summarizes_others(water):
    # Choosing the first/largest part, or dropping detached parts, misreports this seed.
    assert check_seed(water, Point(11, 3)) == {
        'status': 'pass',
        'containing_component_index': 1,
        'boundary_component_indices': [],
        'unseeded_components': [
            {'index': 0, 'bounds': [0, 0, 8, 8], 'planar_area': 64},
            {'index': 2, 'bounds': [16, 6, 19, 8], 'planar_area': 6},
        ],
    }


@pytest.mark.parametrize(('xy', 'status', 'boundary'), [
    # Testing only exterior shells would fill the island hole.
    pytest.param((13, 3), 'outside', [], id='island-hole-interior'),
    # Testing only the multipart bounding box would accept the gap.
    pytest.param((9, 3), 'outside', [], id='gap-between-components'),
    # A boundary-inclusive covers check would accept these as interior.
    pytest.param((10, 3), 'ambiguous', [1], id='outer-edge'),
    # Looking only at exterior rings for ambiguity would miss the hole edge.
    pytest.param((12, 3), 'ambiguous', [1], id='island-hole-edge'),
    # Taking the first boundary hit would hide the second touching component.
    pytest.param((16, 6), 'ambiguous', [1, 2], id='shared-vertex'),
])
def test_non_interior_leaves_every_component_unseeded(water, xy, status, boundary):
    report = check_seed(water, Point(*xy))
    assert report['status'] == status
    assert report['containing_component_index'] is None
    assert report['boundary_component_indices'] == boundary
    assert [part['index'] for part in report['unseeded_components']] == [0, 1, 2]


def test_overlapping_parts_are_refused_instead_of_picking_one():
    # Without validity checking, the seed in two interiors could silently pick one.
    overlap = MultiPolygon([box(0, 0, 4, 4), box(2, 2, 6, 6)])
    with pytest.raises(ValueError, match='candidate water geometry'):
        check_seed(overlap, Point(3, 3))

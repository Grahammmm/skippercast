"""Check offline probe pins against the tracked North B forecast inputs."""

import pytest

from skippercast.platform.contracts import bbox, read_json
from tests._support import ROOT

FIXTURE = ROOT / 'docs/operations/fixtures/north-b-offshore-review-points.json'
ARENA = 'fort-bragg-point-arena'
SHELTER = 'shelter-cove-north-mendocino'
HUMBOLDT = 'humboldt-bay-cape-mendocino'


@pytest.fixture
def review_points():
    return read_json(FIXTURE)['regions']


def _expected_pin(region):
    west, south, east, north = bbox(region['bounds'])
    for point in region['forecast_points']:
        lon, lat = point['longitude'], point['latitude']
        if point.get('offshore') is True and west <= lon <= east and south <= lat <= north:
            return {'status': 'pinned', 'sample_id': point['id'], 'longitude': lon, 'latitude': lat}
    return {'status': 'unavailable'}


def _check_review_points(review_points):
    assert review_points.keys() == {ARENA, SHELTER, HUMBOLDT}
    for region_id, pin in review_points.items():
        region = read_json(ROOT / 'regions' / region_id / 'region.json')
        assert region['id'] == region_id
        assert pin == _expected_pin(region), f'{region_id}: pin differs from tracked forecast metadata'


def test_pins_match_tracked_north_b_forecast_metadata(review_points):
    # Catches omitted regions, nearshore substitutions, or a fabricated Shelter Cove pin.
    _check_review_points(review_points)


def test_rejects_sample_from_wrong_region(review_points):
    # Two valid pins swapped under intact region keys must not pass a global sample lookup.
    review_points[ARENA], review_points[HUMBOLDT] = review_points[HUMBOLDT], review_points[ARENA]
    with pytest.raises(AssertionError, match=f'{ARENA}: pin differs'):
        _check_review_points(review_points)


def test_rejects_stale_sample_coordinate(review_points):
    # An old coordinate can still be in bounds and have the correct sample ID.
    review_points[ARENA]['longitude'] += 0.001
    with pytest.raises(AssertionError, match=f'{ARENA}: pin differs'):
        _check_review_points(review_points)


def test_selection_skips_out_of_frame_and_keeps_recorded_order():
    # Catches taking the first flagged point regardless of frame, or sorting eligible IDs.
    region = {
        'bounds': [-125, 38, -123, 40],
        'forecast_points': [
            {'id': 'outside', 'longitude': -126, 'latitude': 39, 'offshore': True},
            {'id': 'z-first', 'longitude': -124, 'latitude': 39, 'offshore': True},
            {'id': 'a-later', 'longitude': -124.5, 'latitude': 39, 'offshore': True},
        ],
    }
    assert _expected_pin(region) == {
        'status': 'pinned', 'sample_id': 'z-first', 'longitude': -124, 'latitude': 39,
    }

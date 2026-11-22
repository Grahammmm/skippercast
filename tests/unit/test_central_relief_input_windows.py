"""Check the inert review manifest against the tracked region config files."""

import json

import pytest

from tests._support import ROOT

MANIFEST = ROOT / 'docs/operations/fixtures/central-relief-input-windows.json'
CENTRAL_IDS = (
    'big-sur-coast',
    'cambria-san-simeon',
    'south-big-sur-san-simeon',
    'monterey-point-sur',
    'point-arguello-conception',
    'santa-cruz-monterey-bay',
)


@pytest.fixture
def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def _check_windows(manifest):
    assert manifest['crs'] == 'WGS84'
    assert manifest['bounds_order'] == ['west', 'south', 'east', 'north']
    windows = manifest['windows']
    assert windows.keys() == set(CENTRAL_IDS)
    for region_id in CENTRAL_IDS:
        path = f'regions/{region_id}/region.json'
        config = json.loads((ROOT / path).read_text(encoding='utf-8'))
        assert config['id'] == region_id
        row = windows[region_id]
        assert row['region_config'] == path, f'{region_id}: wrong region.json provenance'
        assert row['fishing_bounds'] == config['fishing_bounds'], (
            f'{region_id}: fishing_bounds differ from {path}'
        )


def test_manifest_matches_six_tracked_fishing_windows(manifest):
    # An omitted region, wrong citation, or copy of broad `bounds` instead of
    # `fishing_bounds` would give the reviewer the wrong reference window.
    _check_windows(manifest)


def test_rejects_swapped_neighboring_windows(manifest):
    # The same two valid windows under each other's IDs must fail even though
    # the roster, provenance paths, and unordered set of bounds are unchanged.
    north = manifest['windows']['monterey-point-sur']
    south = manifest['windows']['big-sur-coast']
    north['fishing_bounds'], south['fishing_bounds'] = (
        south['fishing_bounds'], north['fishing_bounds']
    )
    with pytest.raises(AssertionError, match='big-sur-coast: fishing_bounds differ'):
        _check_windows(manifest)


def test_rejects_changed_edge(manifest):
    # A small edge expansion can still look plausible and keep the right ID;
    # review must use the exact configured box, not a close or overlapping one.
    manifest['windows']['cambria-san-simeon']['fishing_bounds'][0] -= 0.001
    with pytest.raises(AssertionError, match='cambria-san-simeon: fishing_bounds differ'):
        _check_windows(manifest)

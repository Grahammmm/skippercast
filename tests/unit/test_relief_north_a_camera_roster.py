"""Bind the inert North A QA roster to the checked-in preview loader."""
from collections import Counter

import pytest

from skippercast.relief import render_config
from skippercast.relief.package import decode_document
from tests._support import ROOT


REGIONS = ('point-arena-bodega', 'bodega-point-reyes', 'point-reyes-pigeon')
PURPOSE_ZOOM = {'harbor_orientation': 13, 'shelf_detail': 15}


@pytest.fixture
def roster(monkeypatch):
    # Use the checkout's inputs even if the caller has a configured data root.
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(ROOT))
    path = ROOT / 'docs/operations/fixtures/relief-north-a-camera-roster.json'
    return decode_document(path.read_bytes())


def _check_assignments(region, groups):
    previews = {row['id']: row for row in render_config.previews(region)}
    assert groups.keys() == PURPOSE_ZOOM.keys()
    assigned = Counter()
    for purpose, rows in groups.items():
        for row in rows:
            preview_id = row['preview_id']
            assert preview_id in previews, f'{region}: unconfigured preview {preview_id}'
            assert previews[preview_id]['zoom'] == PURPOSE_ZOOM[purpose], (
                f'{preview_id}: wrong viewport purpose {purpose}'
            )
            assigned[preview_id] += 1
    assert assigned == Counter(previews.keys()), f'{region}: expected exactly one assignment per preview'


def test_roster_covers_all_north_a_regions_and_previews(roster):
    # Catches a dropped region, stale ID, or valid camera filed under the wrong purpose.
    assert roster['regions'].keys() == set(REGIONS)
    for region, groups in roster['regions'].items():
        _check_assignments(region, groups)


@pytest.mark.parametrize('count', [0, 2], ids=['omitted-camera', 'duplicated-camera'])
def test_assignment_requires_exactly_one_entry(roster, count):
    # A membership-only or set-only check could accept a missing or repeated camera.
    region = 'point-reyes-pigeon'
    groups = roster['regions'][region]
    groups['shelf_detail'] *= count
    with pytest.raises(AssertionError, match='exactly one assignment per preview'):
        _check_assignments(region, groups)


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_theme_variant_is_not_a_camera_id(roster, theme):
    # Adding a themed copy must not expand the configured camera inventory.
    region = 'point-reyes-pigeon'
    groups = roster['regions'][region]
    row = groups['shelf_detail'][0]
    variant_id = f"{row['preview_id']}-{theme}"
    groups['shelf_detail'].append({**row, 'preview_id': variant_id})
    with pytest.raises(AssertionError, match=f'unconfigured preview {variant_id}'):
        _check_assignments(region, groups)


def test_valid_preview_id_is_rejected_under_another_region(roster):
    # These harbor cameras share a center and zoom. A global or geometry-based lookup
    # could accept the neighboring region's ID without losing a viewport slot.
    owner = 'bodega-point-reyes'
    target = 'point-arena-bodega'
    _check_assignments(owner, roster['regions'][owner])
    foreign, = roster['regions'][owner]['harbor_orientation']
    groups = roster['regions'][target]
    groups['harbor_orientation'] = [foreign]
    with pytest.raises(AssertionError, match=f"{target}: unconfigured preview {foreign['preview_id']}"):
        _check_assignments(target, groups)


def test_evidence_slots_are_separate_empty_and_inert(roster):
    # Catches conflating reviewer location with survey support or adding a readiness flag.
    assert roster.keys() == {'description', 'regions'}
    for groups in roster['regions'].values():
        for rows in groups.values():
            for row in rows:
                assert row == {
                    'preview_id': row['preview_id'],
                    'reviewer_location_evidence': None,
                    'survey_support_evidence': None,
                }

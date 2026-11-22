"""Exercise the release reader and the saved Coverage index at the audit boundary."""

import json

import pytest

from scripts.relief.coverage_roster_audit import audit_roster

MORRO = {'id': 'morro-bay', 'name': 'Morro Bay', 'status': 'active', 'fishing_bounds': [-122, 35, -121, 36]}
SOCAL = {'id': 'southern-california', 'name': 'Southern California', 'status': 'preview',
         'fishing_bounds': [-120, 32, -117, 35]}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


@pytest.fixture
def audit(tmp_path):
    release_root = tmp_path / 'checkout'
    _write(release_root / 'dist/regions/index.json', {'regions': [{'id': 'morro-bay'}, {'id': 'southern-california'}]})
    # The real loader reads source bounds for the release IDs, anchors and islands.
    for region_id in ('morro-bay', 'southern-california', 'san-diego', 'crescent-city',
                      'channel-islands-north', 'outer-islands-borderland'):
        _write(release_root / 'regions' / region_id / 'region.json', {'bounds': [-124, 32, -117, 42]})
    saved_index = tmp_path / 'saved/regions/index.json'

    def run(*rows):
        _write(saved_index, {'regions': rows})
        return audit_roster(release_root, saved_index)

    return run


def test_active_and_preview_release_rows_are_discoverable_not_live(audit):
    # Exact-ID release membership accepts both public statuses; active must not imply M9 live.
    result = audit(SOCAL, MORRO)
    assert result['release_roster_ok'] is True
    assert result['release_ids'] == ['morro-bay', 'southern-california']
    assert result['missing_release_ids'] == []
    assert result['duplicate_release_ids'] == {}
    assert result['invalid_rows'] == []
    assert [(row['id'], row['public_status'], row['kind']) for row in result['selectable_rows']] == [
        ('southern-california', 'preview', 'release'), ('morro-bay', 'active', 'release'),
    ]
    assert result['m9_live_state'] == 'not_evaluated'


def test_one_missing_release_id_is_reported(audit):
    # A nonempty fixture must not pass merely because all of its own rows are valid.
    result = audit(SOCAL)
    assert result['release_roster_ok'] is False
    assert result['missing_release_ids'] == ['morro-bay']
    assert result['duplicate_release_ids'] == {}


@pytest.mark.parametrize('second', [MORRO, dict(MORRO, name='')], ids=['valid', 'invalid'])
def test_duplicate_release_id_counts_before_filtering(audit, second):
    # A dict keyed by ID or a filter-first count would silently lose a second occurrence.
    result = audit(MORRO, SOCAL, second)
    assert result['release_roster_ok'] is False
    assert result['missing_release_ids'] == []
    assert result['duplicate_release_ids'] == {'morro-bay': 2}


def test_island_preview_children_do_not_replace_southern_california(audit):
    # Child names/bounds can coincide with the parent; only its exact ID fills its slot.
    north = dict(SOCAL, id='channel-islands-north', name='Northern Channel Islands')
    outer = dict(SOCAL, id='outer-islands-borderland')
    result = audit(MORRO, north, outer)
    assert result['release_roster_ok'] is False
    assert result['missing_release_ids'] == ['southern-california']
    assert [(row['id'], row['kind'], row['public_status']) for row in result['selectable_rows'][1:]] == [
        ('channel-islands-north', 'non_release_preview', 'preview'),
        ('outer-islands-borderland', 'non_release_preview', 'preview'),
    ]
    assert audit(MORRO, SOCAL, north, outer)['release_roster_ok'] is True


@pytest.mark.parametrize('defect', [
    {'name': '  '}, {'status': 'draft'}, {'fishing_bounds': [-120, False, -117, 35]},
], ids=['blank-name', 'draft-status', 'non-numeric-bounds'])
def test_present_but_unselectable_release_row_fails(audit, defect):
    # Presence is not discoverability: Coverage needs a label, a public status and numeric bounds.
    result = audit(MORRO, dict(SOCAL, **defect))
    assert result['release_roster_ok'] is False
    assert result['missing_release_ids'] == []
    assert result['invalid_release_ids'] == ['southern-california']
    assert result['invalid_rows'] == [1]
    assert [row['id'] for row in result['selectable_rows']] == ['morro-bay']


def test_noncanonical_id_cannot_be_normalized_into_a_release_match(audit):
    # Trimming or case folding would credit a row whose actual link targets the wrong ID.
    result = audit(MORRO, dict(SOCAL, id='Southern-California '))
    assert result['release_roster_ok'] is False
    assert result['missing_release_ids'] == ['southern-california']
    assert result['invalid_rows'] == [1]

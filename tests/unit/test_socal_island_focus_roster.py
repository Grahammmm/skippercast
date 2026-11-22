"""Offline checklist validation against Southern California's parent config."""

import pytest

from skippercast.platform.contracts import read_json
from tests._support import ROOT

ROSTER = ROOT / 'docs/operations/fixtures/socal-island-focus-roster.json'
PARENT = ROOT / 'regions/southern-california/region.json'
# These parent map focuses are useful browsing views but are not individual islands.
NON_ISLAND_FOCUSES = {'north-islands', 'san-diego', 'orange-county'}


@pytest.fixture
def checklist():
    return read_json(ROSTER), read_json(PARENT)


def validate_checklist(roster, parent, screenshot_focus_by_slot):
    """Audit slot identity, holds and synthetic screenshot attribution, not image content."""
    assert roster['region_id'] == parent['id']
    individual = {
        focus['id']: focus['name'].removesuffix(' Island')
        for focus in parent['map']['focus_areas']
        if focus['id'] not in NON_ISLAND_FOCUSES
    }
    slots = roster['focus_slots']
    missing, unexpected = individual.keys() - slots.keys(), slots.keys() - individual.keys()
    assert not (missing or unexpected), f'missing={sorted(missing)}, unexpected={sorted(unexpected)}'

    held_names = set(parent['habitat_policy']['military_islands_withheld'])
    assert held_names <= set(individual.values()), 'habitat hold does not resolve to an island focus'
    for focus_id, state in slots.items():
        if individual[focus_id] in held_names:
            assert state == 'withheld', f'{focus_id}: habitat policy requires withheld'
        else:
            assert state in {'pending', 'reviewed'}, f'{focus_id}: invalid review status'
            if state == 'reviewed':
                assert screenshot_focus_by_slot.get(focus_id) == focus_id, (
                    f'{focus_id}: requires a screenshot of the same focus'
                )


def test_tracked_roster_accounts_for_each_parent_island_without_claiming_review(checklist):
    # A roster drift or an unbacked review claim must fail on the checked-in bytes.
    validate_checklist(*checklist, screenshot_focus_by_slot={})


@pytest.mark.parametrize('add_focus', [None, 'north-islands', 'san-diego'], ids=[
    'missing-anacapa', 'umbrella-is-not-a-substitute', 'mainland-is-not-a-substitute',
])
def test_missing_anacapa_cannot_be_hidden_by_another_focus(checklist, add_focus):
    # Counting rows alone misses a dropped island replaced with a non-island view.
    roster, parent = checklist
    roster['focus_slots'].pop('anacapa')
    if add_focus is not None:
        roster['focus_slots'][add_focus] = 'pending'
    with pytest.raises(AssertionError, match=r"missing=\['anacapa'\]") as error:
        validate_checklist(roster, parent, screenshot_focus_by_slot={})
    if add_focus is not None:
        assert f'unexpected={[add_focus]}' in str(error.value)


@pytest.mark.parametrize('focus_id', ['san-clemente', 'san-nicolas'])
def test_withheld_island_cannot_be_promoted_even_with_a_matching_screenshot(checklist, focus_id):
    # A reviewer must not replace a policy hold with review status based on a screenshot.
    roster, parent = checklist
    roster['focus_slots'][focus_id] = 'reviewed'
    with pytest.raises(AssertionError, match=f'{focus_id}: habitat policy requires withheld'):
        validate_checklist(roster, parent, screenshot_focus_by_slot={focus_id: focus_id})


@pytest.mark.parametrize('screenshot_focus', ['anacapa', 'san-diego', 'north-islands'])
def test_anacapa_review_requires_anacapa_screenshot(checklist, screenshot_focus):
    # A region-level evidence check could accept a mainland or umbrella screenshot.
    roster, parent = checklist
    roster['focus_slots']['anacapa'] = 'reviewed'
    evidence = {'anacapa': screenshot_focus}
    if screenshot_focus == 'anacapa':
        validate_checklist(roster, parent, evidence)
    else:
        with pytest.raises(AssertionError, match='anacapa: requires a screenshot of the same focus'):
            validate_checklist(roster, parent, evidence)

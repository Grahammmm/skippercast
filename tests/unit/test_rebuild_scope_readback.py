"""Replay reviewed intent and observed identities without running a stage."""

import pytest

from scripts.relief.rebuild_scope_check import REQUIRED_STAGES
from scripts.relief.rebuild_scope_readback import compare

REGION = 'replay-bay'
OLD, NEW = '1' * 64, '2' * 64


@pytest.fixture
def replay():
    rebuilds = {'tiles.public', 'digests'}
    stages = sorted(REQUIRED_STAGES)
    plan = {
        'regions': [{'region': REGION, 'stages': [
            {'stage': key, 'action': 'rebuild', 'reasons': ['synthetic change']}
            if key in rebuilds else {'stage': key, 'action': 'reuse', 'reasons': []}
            for key in stages
        ]}],
        'summary': {'regions': 1, 'rebuild_heavy': 1},
    }
    return {
        'plan': plan,
        'ceiling': {REGION: ['tiles.public', 'digests', 'inventory']},
        'expected_regions': [REGION],
        'expected_stages': {REGION: stages},
        'before': {REGION: dict.fromkeys(stages, OLD)},
        'after': {REGION: dict.fromkeys(stages, OLD)},
    }


def test_replay_distinguishes_plan_intent_from_observed_changes(replay):
    """Catch treating every allowed pair as planned or unchanged bytes as proof of a rebuild."""
    replay['before'][REGION].update({'tiles.public': None, 'tiles.private': OLD})
    replay['after'][REGION].update({'tiles.public': NEW, 'tiles.private': None, 'inventory': NEW})
    assert compare(**replay) == {
        'observed_planned': [
            {'region': REGION, 'stage': 'tiles.public', 'before': None, 'after': NEW},
        ],
        'unexpected_observed': [
            {'region': REGION, 'stage': 'inventory', 'before': OLD, 'after': NEW,
             'outside_ceiling': False, 'planned_action': 'reuse'},
            {'region': REGION, 'stage': 'tiles.private', 'before': OLD, 'after': None,
             'outside_ceiling': True, 'planned_action': None},
        ],
        'planned_unobserved': [
            {'region': REGION, 'stage': 'digests', 'before': OLD, 'after': OLD},
        ],
    }


def test_readback_refuses_a_plan_the_scope_check_did_not_accept(replay):
    """Catch bypassing the scope-check result when every digest looks unchanged."""
    replay['ceiling'][REGION].remove('digests')
    with pytest.raises(ValueError, match='requires a plan within the review ceiling'):
        compare(**replay)


@pytest.mark.parametrize('missing_from', [('after',), ('before', 'after')])
def test_missing_observation_is_not_explicit_absence(replay, missing_from):
    """Catch treating a missing key as a removal or ignoring a planned pair missing on both sides."""
    for side in missing_from:
        replay[side][REGION].pop('tiles.public')
    with pytest.raises(ValueError, match='include every plan pair'):
        compare(**replay)


def test_invalid_identity_is_not_evidence(replay):
    """Catch reporting an arbitrary label as an observed digest change."""
    replay['after'][REGION]['inventory'] = 'unreadable'
    with pytest.raises(ValueError, match='expected a SHA-256 digest'):
        compare(**replay)

"""F30-01: independent four128 review uses the admitted scientific policy."""
import sys
from unittest.mock import patch

import pytest

from skippercast.coastal.authenticated_v1.policy import evaluate
from skippercast.coastal.authenticated_v1.profiles import CONTAINED, PARTIAL_SUPPORT, grant_identity
from skippercast.coastal.handoff.common import digest
from tests.unit.test_coastal_four128_home_paths import _load
from tests.unit.test_coastal_partial_support import (
    LARGER_WINDOWS, PARTIAL_WINDOWS, _grant, _ordered, _partial_packet,
)


@pytest.fixture
def review(monkeypatch):
    # The research scripts adjust imports for the standalone control lanes.
    monkeypatch.setattr(sys, 'dont_write_bytecode', sys.dont_write_bytecode)
    with patch.dict(sys.modules):
        yield _load('coastal_four128_artifact_review', {})[0]


def _case(partial, good_pairs):
    grant = _grant(PARTIAL_WINDOWS if partial else LARGER_WINDOWS, **_ordered())
    packet = _partial_packet(grant, grant['window_set'][0])
    if partial:
        grant['support_policy'] = packet['support_policy'] = PARTIAL_SUPPORT
    frozen = {'grant_identity': grant_identity(grant)}
    facts = dict(header=dict(driver='BAG', scales=[1, 1], offsets=[0, 0], units=['m', 'm']))
    counts: dict[str, int] = dict.fromkeys(
        ('paired_mask_valid', 'paired_raw_finite', 'source_pair_valid', 'normalized_finite', 'eligible'),
        good_pairs,
    )
    counts['returned_paired_cells'] = 128 * 128
    counts['mask_invalid'] = 128 * 128 - good_pairs
    diag = dict(counts=counts, facts_digest=digest(facts), uncertainty=dict(
        units='m', count=good_pairs, minimum=0.5, maximum=0.5, nonpositive=0, above_1m=0))
    diag['diagnostics_digest'] = digest(diag)
    produced = evaluate(diag, facts, execution_profile=CONTAINED, configuration=packet)
    produced['trial_policy_sha256'] = digest({'synthetic_trial_policy': partial})
    policy_binding = {key: produced[key] for key in ('policy_sha256', 'trial_policy_sha256')}
    packet.update(policy_binding)
    return grant, packet, frozen, diag, facts, policy_binding, produced


@pytest.mark.parametrize('partial,good_pairs,holds', [
    (True, 16_000, []),
    (False, 16_384, []),
    (False, 16_000, ['bounded_patch_nominal_depth_out_of_range',
                     'bounded_patch_nominal_support_incomplete',
                     'bounded_patch_uncertainty_quality_failed']),
])
def test_recomputes_granted_policy(review, partial, good_pairs, holds):
    *inputs, produced = _case(partial, good_pairs)
    observed = review.review_policy(*inputs)
    assert observed['holds'] == holds
    assert observed['accepted'] is False
    assert digest(observed) == digest(produced)


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('where,reason', [
    ('result', 'scientific policy digest'),
    ('packet', 'packet support policy differs'),
    ('frozen', 'grant differs from frozen preparation'),
    ('trial', 'trial policy digest'),
])
def test_refuses_swapped_policy(review, partial, where, reason):
    grant, packet, frozen, diag, facts, result, _ = _case(partial, 16_000 if partial else 16_384)
    _, other_packet, other_frozen, _, _, other_result, _ = _case(not partial, 16_384 if partial else 16_000)
    if where == 'result':
        result['policy_sha256'] = other_result['policy_sha256']
    elif where == 'packet':
        packet['support_policy'] = other_packet.get('support_policy')
    elif where == 'frozen':
        frozen = other_frozen
    else:
        result['trial_policy_sha256'] = other_result['trial_policy_sha256']
    with pytest.raises(ValueError, match=reason):
        review.review_policy(grant, packet, frozen, diag, facts, result)

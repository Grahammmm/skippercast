"""F20-14 / SCA-223: a proposed Estero Bluffs shore selection needs affirmative evidence for both prerequisites.

Contract: m2EsteroBluffs.selectionState 'proposed' is refused when siteSelectionLimits or ownerUrl is
failed or unverifiable, each field judged on its own; the same evidence under 'unresolved' with a dependent
hold stays valid. Believable bug: the validator rejecting only 'unverifiable' lets a failed owner URL or
failed limits ride a structurally green proposal. Structural validation only; offline, synthetic data.
"""
import copy

import pytest

from tests.contract.test_shore_reread_dossier import H, checker, dossier

FIELDS = ('siteSelectionLimits', 'ownerUrl')
CAND = {'objectId': 2255, 'esi': '1A', 'esiLegend': [{'code': '1A', 'legend': 'Exposed rocky shores'}],
        'coordinatesSha256': H('9'), 'vertices': 20}


def proposed(**states):
    doc = dossier()
    est = doc['m2EsteroBluffs']
    est['selectionState'] = 'proposed'
    est['candidates'] = [copy.deepcopy(CAND)]
    for k in FIELDS:
        est[k] = {'state': states.get(k, 'unchanged'), 'basis': 'read from the owner record'}
    return doc


def test_positive_control_affirmative_evidence_proposal_is_accepted():
    assert checker.check(proposed()) == []
    assert checker.check(proposed(siteSelectionLimits='changed', ownerUrl='unchanged')) == []


@pytest.mark.parametrize('field', FIELDS)
@pytest.mark.parametrize('state', ('failed', 'unverifiable'))
def test_each_prerequisite_alone_blocks_a_proposal(field, state):
    errors = checker.check(proposed(**{field: state}))
    assert errors == [f'm2EsteroBluffs.{field}: {state}, selection must stay unresolved']


@pytest.mark.parametrize('field', FIELDS)
def test_failed_evidence_stays_valid_only_as_unresolved_with_hold(field):
    doc = proposed(**{field: 'failed'})
    doc['m2EsteroBluffs']['selectionState'] = 'unresolved'
    assert checker.check(doc) == []
    doc['m2EsteroBluffs']['dependentHold'] = ' '
    assert any('must state the held dependent work' in e for e in checker.check(doc))

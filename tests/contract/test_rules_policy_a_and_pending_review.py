"""SC2184-02/03: policy-A is enforced by the binding check, and the committed review decision stays unapproved."""
from copy import deepcopy
import json
import pytest

from skippercast.pipeline.regulation_review import approved_registry, jurisdiction_files
from skippercast.pipeline.regulations import content_hash, validate_bindings, regional_source_ids
from tests._support import ROOT

PENDING = ROOT / 'jurisdictions/reviews/PENDING-2026-11-13-california-central.json'


@pytest.fixture
def central():
    jurisdiction, registry, _ = jurisdiction_files('california-central', ROOT)
    return jurisdiction, registry


def test_committed_central_policy_a(central):
    jurisdiction, registry = central
    assert set(jurisdiction['required_source_ids']) == {'rules-inseason', 'rules-book'}
    assert jurisdiction['species_required_source_ids'] == {'dungeness': ['rules-health']}
    assert set(jurisdiction['also_check_source_ids']) == {'rules-proposals', 'rules-health'}
    for ident, profile in registry['species'].items():
        assert 'rules-proposals' not in profile['source_ids'] and 'rules-proposals' in profile['also_check_source_ids']
        assert ('rules-health' in profile['source_ids']) == (ident == 'dungeness')
        assert {'rules-inseason', 'rules-book'} <= set(profile['source_ids'])
    assert {'rules-proposals', 'rules-health'} <= set(regional_source_ids(jurisdiction, registry, {
        'id': 'morro-bay', 'jurisdiction_id': 'california-central', 'assets': {'regulations': jurisdiction['regulations_asset']},
        **json.loads((ROOT / 'dist/regions/morro-bay/region.json').read_text())}))


@pytest.mark.parametrize('mutate, message', [
    (lambda r: r['species']['dungeness']['source_ids'].remove('rules-health'), 'Missing shared legal dependencies'),
    (lambda r: r['species']['salmon']['source_ids'].remove('rules-inseason'), 'Missing shared legal dependencies'),
    (lambda r: r['species']['salmon']['source_ids'].remove('rules-book'), 'Missing shared legal dependencies'),
    (lambda r: r['species']['salmon'].update(also_check_source_ids=['rules-proposals']), 'Also-check links'),
    (lambda r: r['species']['dungeness'].update(also_check_source_ids=['rules-proposals', 'rules-health']), 'Also-check links'),
    (lambda r: r['species']['halibut'].update(also_check_source_ids=['rules-proposals', 'rules-health', 'rules-gear']), 'Also-check links'),
])
def test_binding_refuses_drift_from_policy_a(central, mutate, message):
    jurisdiction, registry = central
    registry = deepcopy(registry)
    mutate(registry)
    with pytest.raises(ValueError, match=message):
        validate_bindings(jurisdiction, registry)


def test_inseason_cannot_be_demoted_to_a_link(central):
    jurisdiction, registry = central
    jurisdiction = deepcopy(jurisdiction)
    jurisdiction['also_check_source_ids'].append('rules-inseason')
    with pytest.raises(ValueError, match='cannot both block'):
        validate_bindings(jurisdiction, registry)


def test_pending_decision_is_unapproved_and_apply_refuses_it(central):
    jurisdiction, registry = central
    decision = json.loads(PENDING.read_text())
    assert decision['jurisdiction_id'] == 'california-central'
    assert decision['rules_content_sha256'] == content_hash(registry)
    assert set(decision['sources']) == set(registry['sources'])
    assert decision['reviewed_at'] is None and decision['revision'] is None
    for ident, choice in decision['sources'].items():
        assert choice['decision'] is None and choice['content_sha256'] is None and choice['note'] == '', ident
    assert 'approve"' not in PENDING.read_text().replace('approve or hold', '')
    packet = {'jurisdiction_id': 'california-central', 'sources': {}}
    with pytest.raises(ValueError):
        approved_registry(registry, jurisdiction, packet, decision)


def test_one_unset_source_alone_still_refuses(central):
    """Everything filled in but one source left unset: still refused."""
    from datetime import datetime, timezone
    jurisdiction, registry = central
    now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    packet = {'jurisdiction_id': 'california-central', 'sources': {
        ident: {'status': 'ok', 'url': spec['url'], 'data_retrieved_at': '2026-11-20T10:00:00Z',
                'data': {'content_sha256': 'a' * 64, 'normalization': spec['normalization']}}
        for ident, spec in registry['sources'].items()}}
    decision = {'jurisdiction_id': 'california-central', 'revision': 'test', 'reviewed_at': '2026-11-20T11:00:00Z',
                'rules_content_sha256': content_hash(registry), 'reviewed_species': list(registry['species']),
                'sources': {ident: {'decision': 'hold', 'content_sha256': 'a' * 64, 'note': 'held in a test, nothing approved'}
                            for ident in registry['sources']}}
    approved_registry(registry, jurisdiction, packet, decision, now)  # all explicit (hold) is accepted
    decision['sources']['rules-salmon']['decision'] = None
    with pytest.raises(ValueError, match='Choose approve or hold for rules-salmon'):
        approved_registry(registry, jurisdiction, packet, decision, now)

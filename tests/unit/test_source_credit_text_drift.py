"""Synthetic register snapshots at the offline comparator boundary."""
import pytest

from scripts import build_sources_register as register
from scripts.relief.source_credit_text_drift import CreditFinding, CreditText, compare


def row(source_id, *, name='Fixture shelf', provider='Fixture Hydrography', attribution='© Fixture & Partners'):
    return {'id': source_id, 'name': name, 'provider': provider, 'rights': {'attribution': attribution}}


def test_same_id_attribution_change_is_reported():
    """An ID-only comparison misses a verbatim edit (even just punctuation)."""
    before = {'sources': [row('shelf')]}
    after = {'sources': [row('shelf', attribution='© Fixture & Partners.')]}
    assert compare(before, after, ['shelf']) == (
        CreditFinding('shelf', CreditText('Fixture shelf', 'Fixture Hydrography', '© Fixture & Partners', None),
                      CreditText('Fixture shelf', 'Fixture Hydrography', '© Fixture & Partners.', None)),
    )


def test_same_id_credit_heading_change_includes_supplemental_credit():
    """Comparing just rights.attribution would miss the new displayed agency and its supplemental credit."""
    before = {'sources': [row('shelf')]}
    after = {'sources': [row('shelf', name='Fixture bank', provider='CSUMB Fixture Lab')]}
    assert compare(before, after, ['shelf']) == (
        CreditFinding('shelf', CreditText('Fixture shelf', 'Fixture Hydrography', '© Fixture & Partners', None),
                      CreditText('Fixture bank', 'CSUMB Fixture Lab', '© Fixture & Partners', register.CSUMB_CREDIT)),
    )


def test_reorder_only_is_unchanged():
    """Comparing rows by position would report two false changes."""
    shelf, bank = row('shelf'), row('bank', attribution='Fixture Bank Lab')
    assert compare({'sources': [shelf, bank]}, {'sources': [bank, shelf]}, ['shelf', 'bank']) == ()


def test_unreviewed_and_noncredit_changes_are_ignored():
    """A whole-register or whole-row diff would conflate unrelated changes with credit drift."""
    before = {'sources': [row('shelf'), row('bank')]}
    after = {'sources': [dict(row('shelf'), survey_year=2020), row('bank', attribution='Other credit')]}
    assert compare(before, after, ['shelf']) == ()


@pytest.mark.parametrize('target_present', [True, False], ids=['missing-attribution', 'missing-source-id'])
def test_missing_credit_is_not_borrowed_from_a_different_provider(target_present):
    """Joining by display name or falling back to a provider would hide the missing credit."""
    target = row('shelf')
    decoy = row('other-shelf', provider='Different Fixture Provider')
    before = {'sources': [target, decoy]}
    missing = {**target, 'rights': {}}
    after = {'sources': [decoy, missing] if target_present else [decoy]}
    assert compare(before, after, ['shelf']) == (
        CreditFinding('shelf', CreditText('Fixture shelf', 'Fixture Hydrography', '© Fixture & Partners', None),
                      CreditText('Fixture shelf', 'Fixture Hydrography', None, None) if target_present else None),
    )


def test_already_missing_credit_stays_visible():
    """An equality-only check can incorrectly make two missing credits look complete."""
    snapshot = {'sources': [row('shelf', attribution='')]}
    missing = CreditText('Fixture shelf', 'Fixture Hydrography', None, None)
    assert compare(snapshot, snapshot, ['shelf']) == (CreditFinding('shelf', missing, missing),)


def test_duplicate_reviewed_id_is_ambiguous():
    """Last-row-wins lookup makes credit depend on the order of duplicate IDs."""
    before = {'sources': [row('shelf')]}
    after = {'sources': [row('shelf'), row('shelf', attribution='Conflicting credit')]}
    with pytest.raises(ValueError, match='duplicate reviewed source ID'):
        compare(before, after, ['shelf'])

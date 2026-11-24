"""verify_review refuses a damaged receipt or review by name, never by KeyError.

Contract: a normalized source reaches a habitat run only if every reviewed field
matches. A field missing from either side is a difference (a refusal), and a
malformed raster_identity is a named refusal, not an AttributeError crash.
"""
import pytest

from skippercast.seafloor import normalized

FIELDS = ('source_sha256', 'requested_bounds_wgs84', 'native_resolution_m',
          'vertical_datum', 'valid_pixels_in_requested_bounds',
          'nominal_0_300ft_pixels_in_requested_bounds')
RECEIPT = {'source_sha256': 'a', 'requested_bounds_wgs84': [0, 0, 1, 1],
           'native_resolution_m': 1, 'vertical_datum': 'x',
           'valid_pixels_in_requested_bounds': 1,
           'nominal_0_300ft_pixels_in_requested_bounds': 1, 'cog_sha256': 'c'}
DERIVED = {'adapter_version': 'measured-multibeam-grid-v1', 'grid_spacing_m': 2,
           'native_sampling': 'bin', 'preparation_receipt_sha256': 'p'}


def _without(data, field):
    return {k: v for k, v in data.items() if k != field}


def test_matching_review_without_identity_passes():
    # Unaffected control: the healthy pair still returns None (guards over-refusal).
    assert normalized.verify_review(dict(RECEIPT), dict(RECEIPT), 'unused') is None


@pytest.mark.parametrize('field', FIELDS)
def test_field_missing_from_receipt_is_named(field):
    # Bug caught: bare KeyError from the receipt instead of a named refusal.
    with pytest.raises(ValueError, match='^Normalized source differs from reviewed '+field+'$'):
        normalized.verify_review(_without(RECEIPT, field), dict(RECEIPT), 'unused')


@pytest.mark.parametrize('field', FIELDS)
def test_field_missing_from_review_is_named(field):
    # Bug caught: bare KeyError from the review instead of a named refusal.
    with pytest.raises(ValueError, match='^Normalized source differs from reviewed '+field+'$'):
        normalized.verify_review(dict(RECEIPT), _without(RECEIPT, field), 'unused')


@pytest.mark.parametrize('field', FIELDS + ('cog_sha256',))
def test_field_missing_from_both_sides_is_not_equal(field):
    # Bug caught: two absent values compared as equal (e.g. a .get() default of
    # None on each side) silently approve an unreviewed source.
    with pytest.raises(ValueError, match='differs from reviewed'):
        normalized.verify_review(_without(RECEIPT, field), _without(RECEIPT, field), 'unused')


@pytest.mark.parametrize('side', ('receipt', 'review'))
def test_cog_sha256_missing_without_identity_is_refused(side):
    # Bug caught: without raster_identity the manifest hash is the only content
    # gate; a missing value must refuse rather than pass or crash.
    receipt, review = dict(RECEIPT), dict(RECEIPT)
    if side == 'receipt':
        receipt = _without(receipt, 'cog_sha256')
    else:
        review = _without(review, 'cog_sha256')
    with pytest.raises(ValueError, match='^Normalized source differs from reviewed manifest'):
        normalized.verify_review(receipt, review, 'unused')


def test_changed_value_still_refused():
    # Bug caught: the missing-field handling loosening the ordinary mismatch check.
    review = {**RECEIPT, 'vertical_datum': 'other'}
    with pytest.raises(ValueError, match='^Normalized source differs from reviewed vertical_datum$'):
        normalized.verify_review(dict(RECEIPT), review, 'unused')


@pytest.mark.parametrize('identity', ('x', 5, ['v'], True))
def test_non_object_raster_identity_is_malformed(identity):
    # Bug caught: AttributeError ('str' has no attribute 'get') from a damaged review.
    with pytest.raises(ValueError, match='^Reviewed raster identity is malformed$'):
        normalized.verify_review(dict(RECEIPT), {**RECEIPT, 'raster_identity': identity}, 'unused')


def test_matching_identity_passes_without_cog_hash(monkeypatch):
    # Unaffected control: with a matching identity the cog hash is not required,
    # exactly as before; the real identity comparison is stood in by a stub.
    identity = {'version': normalized.VERSION, 'sha256': 'abc'}
    monkeypatch.setattr(normalized, 'raster_identity', lambda path: dict(identity))
    review = {**_without(RECEIPT, 'cog_sha256'), 'raster_identity': dict(identity)}
    assert normalized.verify_review(_without(RECEIPT, 'cog_sha256'), review, 'unused') is None


def test_identity_mismatch_still_refused(monkeypatch):
    # Bug caught: the new malformed check short-circuiting the content comparison.
    identity = {'version': normalized.VERSION, 'sha256': 'abc'}
    monkeypatch.setattr(normalized, 'raster_identity',
                        lambda path: {'version': normalized.VERSION, 'sha256': 'other'})
    with pytest.raises(ValueError, match='^Normalized scientific raster differs from reviewed content$'):
        normalized.verify_review(dict(RECEIPT), {**RECEIPT, 'raster_identity': identity}, 'unused')


@pytest.mark.parametrize('field', ('grid_spacing_m', 'native_sampling', 'preparation_receipt_sha256'))
def test_derived_grid_field_missing_from_receipt_is_named(field):
    # Bug caught: bare KeyError on a derived-grid receipt missing a reviewed field.
    receipt = {**RECEIPT, **_without(DERIVED, field)}
    review = {**RECEIPT, **DERIVED}
    with pytest.raises(ValueError, match='^Derived grid differs from reviewed '+field+'$'):
        normalized.verify_review(receipt, review, 'unused')

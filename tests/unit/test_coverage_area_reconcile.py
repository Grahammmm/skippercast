"""Reconcile producer-shaped JSON using independent, synthetic lattice totals."""

import json

import pytest

from scripts.relief.coverage_area_reconcile import reconcile


_SCOPE = '0-300ft-plus-unknown'


@pytest.fixture
def coverage(tmp_path):
    def save(*, zero=False, drop_unknown=False, unknown_measured=0):
        bands = {
            '0-66ft': dict(measured_m2=25, estimated_m2=5, unsurveyed_m2=10),
            '66-300ft': dict(measured_m2=5, estimated_m2=15, unsurveyed_m2=10),
            'unknown-band': dict(measured_m2=unknown_measured, estimated_m2=0, unsurveyed_m2=30),
        }
        if zero:
            bands = {name: dict.fromkeys(row, 0) for name, row in bands.items()}
        if drop_unknown:
            del bands['unknown-band']
        path = tmp_path / 'depth-coverage.json'
        path.write_text(json.dumps(dict(bands=bands, deepest_m=None if zero else 95,
                                        reaches_300ft=not zero)), encoding='utf-8')
        return path
    return save


def test_equal_bounded_totals_count_unknown_only_as_unsurveyed(coverage):
    # Twenty included 5 m² cells; do not drop unknowns or add them to surveyed area.
    result = reconcile(coverage(), aggregate_m2=100, scope=_SCOPE, tolerance_m2=0)
    assert result['matched'] is True
    assert result['total_m2'] == 100
    assert result['delta_m2'] == 0
    assert result['band_totals_m2'] == {'0-66ft': 40, '66-300ft': 30, 'unknown-band': 30}
    assert result['class_totals_m2'] == dict(measured_m2=30, estimated_m2=20, unsurveyed_m2=50)
    assert result['class_percentages'] == dict(measured=30, estimated=20, unsurveyed=50)


def test_dropped_unknown_band_is_incomplete_even_at_equal_totals(coverage):
    # Matching the surviving rows must not stand in for explicit unknown evidence.
    with pytest.raises(ValueError, match='incomplete.*unknown-band'):
        reconcile(coverage(drop_unknown=True), aggregate_m2=70, scope=_SCOPE, tolerance_m2=0)


def test_explicit_zero_total_has_no_percentages(coverage):
    # Zero evidence is valid here, but must not divide by zero or print fake shares.
    result = reconcile(coverage(zero=True), aggregate_m2=0, scope=_SCOPE, tolerance_m2=0)
    assert result['matched'] is True
    assert result['total_m2'] == result['aggregate_m2'] == 0
    assert result['band_totals_m2']['unknown-band'] == 0
    assert 'class_percentages' not in result


def test_all_water_is_rejected_even_when_the_number_matches(coverage):
    # A numerically equal total from the wrong population cannot certify coverage.
    with pytest.raises(ValueError, match='all-water.*past 300 ft'):
        reconcile(coverage(), aggregate_m2=100, scope='all-water', tolerance_m2=0)


@pytest.mark.parametrize(('aggregate', 'matched'), [(98, True), (102, True), (97, False), (103, False)])
def test_tolerance_is_absolute_and_inclusive(coverage, aggregate, matched):
    # Catch a strict boundary, a signed-only comparison, or percentage-based tolerance.
    result = reconcile(coverage(), aggregate_m2=aggregate, scope=_SCOPE, tolerance_m2=2)
    assert result['delta_m2'] == 100 - aggregate
    assert result['matched'] is matched
    assert ('class_percentages' in result) is matched


def test_survey_credit_in_unknown_band_is_rejected_even_at_equal_totals(coverage):
    # Balanced arithmetic must not legitimize a mislabeled unknown-depth cell.
    with pytest.raises(ValueError, match='unknown-band may only contain unsurveyed water'):
        reconcile(coverage(unknown_measured=10), aggregate_m2=110, scope=_SCOPE, tolerance_m2=0)

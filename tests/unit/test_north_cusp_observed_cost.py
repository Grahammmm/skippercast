import pytest

from scripts.relief.north_cusp_observed_cost import compare_observed_cost


@pytest.fixture
def plan():
    # The two fields consumed from north_cusp_tile_plan.tile_plan's report.
    return {'expected_tile_ids': ['12/10/20', '12/11/20'], 'worst_case_bytes': 800}


def test_complete_expected_set_below_forecast(plan):
    # Catches substituting the forecast for the sum of measured bytes.
    report = compare_observed_cost(plan, [
        {'tile': '12/11/20', 'bytes': 50},
        {'tile': '12/10/20', 'bytes': 100},
    ])

    assert report == {
        'worst_case_bytes': 800,
        'observed_bytes': 150,
        'missing_tile_ids': [],
        'extra_tile_ids': [],
    }


def test_extra_tile_is_reported_but_not_charged_to_plan(plan):
    # Catches adding off-plan bytes and falsely reporting a forecast overrun.
    report = compare_observed_cost(plan, [
        {'tile': '12/10/20', 'bytes': 20},
        {'tile': '12/99/20', 'bytes': 1000},
        {'tile': '12/11/20', 'bytes': 40},
    ])

    assert report['extra_tile_ids'] == ['12/99/20']
    assert report['observed_bytes'] == 60


def test_missing_expected_tile_withholds_observed_total(plan):
    # Catches treating equal row counts as complete despite a missing tile ID.
    report = compare_observed_cost(plan, [
        {'tile': '12/10/20', 'bytes': 100},
        {'tile': '12/99/20', 'bytes': 50},
    ])

    assert report['missing_tile_ids'] == ['12/11/20']
    assert report['observed_bytes'] is None
    assert report['worst_case_bytes'] == 800


def test_duplicate_receipt_cannot_silently_replace_a_byte_count(plan):
    # Catches last-write-wins producing an arbitrary measured total.
    with pytest.raises(ValueError, match='duplicate receipt'):
        compare_observed_cost(plan, [
            {'tile': '12/10/20', 'bytes': 20},
            {'tile': '12/10/20', 'bytes': 40},
            {'tile': '12/11/20', 'bytes': 50},
        ])

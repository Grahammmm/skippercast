"""The measured inverse-projection portability bound is not a spatial epsilon."""
import math

import pytest

from tests.coast_contract_factory import load_helper

validator = load_helper('validate_coast_receipt')


@pytest.mark.parametrize('direction', [-math.inf, math.inf])
@pytest.mark.parametrize('index', range(4))
def test_inverse_projection_two_ulp_boundary(index, direction):
    expected = [-120.59882638724586, 34.41455257638639, -120.5440764768544, 34.459879190790716]
    changed = expected.copy()
    assert validator.inverse_bounds_equal(changed, expected)
    for _ in range(2):
        changed[index] = math.nextafter(changed[index], direction)
        assert validator.inverse_bounds_equal(changed, expected)
    changed[index] = math.nextafter(changed[index], direction)
    assert not validator.inverse_bounds_equal(changed, expected)


@pytest.mark.parametrize('bad', [None, [], [1, 2, 3], [False, 0, 0, 0], [math.nan, 0, 0, 0], [math.inf, 0, 0, 0], ['0', 0, 0, 0]])
def test_inverse_projection_malformed_bounds_refuse(bad):
    assert not validator.inverse_bounds_equal(bad, [0., 0., 0., 0.])

"""Oversized numeric metadata is rejected by validation, not by OverflowError."""

import copy
import math

import pytest

from skippercast.coastal.authenticated_v1.planner import _finite, validate_spec

HUGE = 10**400
SOURCE = {"sha256": "a" * 64}


def _spec():
    return {
        "schema": "skippercast.coastal.authenticated-fixed16x16-spec.v1",
        "source_sha256": SOURCE["sha256"],
        "window_shape": [16, 16],
        "halo": 0,
        "minimum_margin_m": 0.1,
        "center_native": [100.0, 200.0],
        "safety_bbox_native": [90.0, 190.0, 110.0, 210.0],
        "segment": {},
        "legacy_bounds": {},
        "historical_support": {},
    }


def test_healthy_spec_schema_matches_planner():
    from skippercast.coastal.authenticated_v1 import planner

    spec = _spec()
    spec["schema"] = planner.SPEC
    before = copy.deepcopy(spec)
    assert validate_spec(spec, SOURCE) is spec
    assert spec == before


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize(("field", "n"), [("center_native", 2), ("safety_bbox_native", 4)])
def test_validate_spec_rejects_unrepresentable_coordinate_integers(field, n, sign):
    from skippercast.coastal.authenticated_v1 import planner

    for index in range(n):
        spec = _spec()
        spec["schema"] = planner.SPEC
        spec[field][index] = sign * HUGE
        with pytest.raises(ValueError, match="fixed16x16"):
            validate_spec(spec, SOURCE)


@pytest.mark.parametrize("n", [2, 4, 6])
@pytest.mark.parametrize("sign", [1, -1])
def test_finite_rejects_unrepresentable_integer_members(n, sign):
    for index in range(n):
        values = [1.0] * n
        values[index] = sign * HUGE
        assert _finite(values, n) is False


@pytest.mark.parametrize(
    "values",
    [
        [True, 1.0],
        ["1", 1.0],
        [None, 1.0],
        [math.nan, 1.0],
        [math.inf, 1.0],
        [-math.inf, 1.0],
        (1.0, 2.0),
        [1.0],
        [1.0, 2.0, 3.0],
    ],
)
def test_finite_rejects_existing_invalid_values(values):
    assert _finite(values, 2) is False


@pytest.mark.parametrize("values", [[-5, 0], [0.0, 3.5], [10**100, -(10**100)]])
def test_finite_accepts_representable_integer_and_float_controls(values):
    assert _finite(values, 2) is True

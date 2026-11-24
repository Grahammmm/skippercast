"""EC contract helpers refuse bad input by name: CLASS_OF / REASON_OF raise ValueError for a code that is not in
CODES (unknown, unhashable or boolean) and hole_max_cells raises ValueError for a cell size that is not a positive
finite number; every known code and every valid cell size keeps today's value."""
import math
import pytest
from skippercast.platform import seafloor_ec as ec

# Every known code with today's class and reason (pinned independently of ec._NAME / ec._CLASS).
KNOWN = {0: ('nodata', 'nodata'), 10: ('measured', 'measured'), 11: ('measured', 'suspect-shoal'),
         20: ('filled', 'hole'), 21: ('filled', 'pit'), 30: ('verified', 'verified'),
         40: ('unresolved', 'hole'), 41: ('unresolved', 'conflict'), 42: ('unresolved', 'ring-range'),
         43: ('unresolved', 'datum-suspect'), 50: ('masked', 'sentinel')}
# Bad codes: absent integers, a code of the wrong type, booleans (== 0 / 1 in Python), unhashable receipt values.
BAD_CODES = [99, -1, 12, 1, 'measured', None, 10.5, math.nan, True, False, [10], {}, {'code': 10}, {10}, object()]


def test_known_codes_unchanged():
    # Bug caught: the new guard also refuses (or renames) a real code, so measured/filled provenance drifts.
    assert set(KNOWN) == set(ec.CODES.values())
    for code, (cls, reason) in KNOWN.items():
        assert ec.CLASS_OF(code) == cls, code
        assert ec.REASON_OF(code) == reason, code


@pytest.mark.parametrize('code', BAD_CODES, ids=repr)
def test_class_of_refuses_by_name(code):
    # Bug caught: an unhashable code escapes as a bare TypeError, or a boolean is read as code 0/1.
    with pytest.raises(ValueError, match='^unknown provenance code'):
        ec.CLASS_OF(code)


@pytest.mark.parametrize('code', BAD_CODES, ids=repr)
def test_reason_of_refuses_by_name(code):
    # Bug caught: REASON_OF indexes _NAME first and leaks a bare KeyError (99, True) or TypeError ([10]).
    with pytest.raises(ValueError, match='^unknown provenance code'):
        ec.REASON_OF(code)


@pytest.mark.parametrize('cell, expected', [(2.0, 9), (2, 9), (0.5, 9), (8.0, 1), (4.0, 4), (10.0, 0), (1e-200, 9),
                                            (1e-160, 9), (10 ** 400, 0)])
def test_hole_max_cells_valid_sizes_unchanged(cell, expected):
    # Bug caught: the guard rejects or alters a valid size (2.0 m -> 9 is the control; 64 // area below the cap;
    # integers, a huge integer and a cell whose square underflows must not crash either).
    assert ec.hole_max_cells(cell) == expected


@pytest.mark.parametrize('cell', [0, 0.0, -0.0, -1.0, -1, -1e-9, math.nan, math.inf, -math.inf, True, False,
                                  '2', None, [2.0], 2j], ids=repr)
def test_hole_max_cells_refuses_bad_sizes(cell):
    # Bug caught: 0 divides by zero, a negative size silently returns the cap (-1.0 -> 9), NaN dies with a
    # float-conversion error, True is read as a 1 m cell, and a non-number escapes as TypeError.
    with pytest.raises(ValueError, match='^cell size must be a positive finite number$'):
        ec.hole_max_cells(cell)

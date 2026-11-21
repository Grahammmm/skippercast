"""F05-12: a segment origin has one spelling and type, so one cell is one row.

Contract protected: segment() builds the primary identifier from the origin.
Believable bug: a whole-number float (5000.0) is accepted and yields
"seg:3310:5000.0:..." for the same cell as 5000, and its bbox then breaks
planning_cells(), because range() needs integers.
"""
import pytest

from skippercast.coastal.coordinator import segments

ORIGIN = 1_000_000


def test_integral_float_origin_is_the_same_row_as_the_int_origin():
    by_int = segments.segment(ORIGIN, -ORIGIN, region="r")
    by_float = segments.segment(float(ORIGIN), -float(ORIGIN), region="r")
    assert by_float == by_int
    assert by_float["segment_id"] == f"seg:3310:{ORIGIN}:-{ORIGIN}:5000"
    assert all(type(v) is int for v in by_float["bbox"])


def test_accepted_segments_generate_all_400_planning_cells():
    for x0, y0 in ((ORIGIN, -ORIGIN), (float(ORIGIN), 5000.0), (0, 0)):
        cells = segments.planning_cells(segments.segment(x0, y0, region="r"))
        assert len(cells) == 400 and len(set(cells)) == 400


def test_existing_integer_origin_keeps_its_identifier():
    assert segments.segment(10000, 15000, region="r")["segment_id"] == "seg:3310:10000:15000:5000"


@pytest.mark.parametrize("bad", [True, False, 5000.5, float("nan"), float("inf"), "5000", None])
def test_booleans_nonintegral_and_nonnumeric_origins_are_refused(bad):
    with pytest.raises(ValueError):
        segments.segment(bad, 5000, region="r")
    with pytest.raises(ValueError):
        segments.segment(5000, bad, region="r")


def test_off_lattice_origin_is_still_refused():
    with pytest.raises(ValueError, match="5 km lattice"):
        segments.segment(5001.0, 0, region="r")

"""Non-finite corners are gaps, not interpolated contour coordinates."""
import math

import pytest

from skippercast.platform import depth_contours as dc


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
@pytest.mark.parametrize('corner', [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_each_nonfinite_corner_behaves_like_none(bad, corner):
    grid = [[10., 50., 10., 50.], [10., 50., 10., 50.], [10., 50., 10., 50.]]
    r, c = corner
    grid[r][c] = bad
    actual = dc.trace(grid, [30, 60])
    grid[r][c] = None
    assert actual == dc.trace(grid, [30, 60])
    assert actual[30], 'unaffected finite squares must still draw'
    assert all(math.isfinite(v) for lines in actual.values() for line in lines for point in line for v in point)


def test_all_finite_trace_positive_control():
    assert dc.trace([[10., 50.], [10., 50.]], [30]) == {30: [[(0.5, 0.0), (0.5, 1.0)]]}

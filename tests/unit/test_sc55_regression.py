"""SC55: finite exact-level extrema have no contour extent; real lines survive."""
from contextlib import nullcontext
from copy import deepcopy
from itertools import groupby

import pytest

from skippercast.platform import depth_contours as dc


EXTREMA = [
    pytest.param([[0, 30], [30, 0]], id='exact-level-saddle'),
    pytest.param([[0, 0, 0], [0, 30, 0], [0, 0, 0]], id='isolated-exact-maximum'),
]

CASES = [
    pytest.param([[0, 30, 60]] * 4, [30], id='exact-node-slope'),
    pytest.param([[0, 30, 60], [30, 60, 90], [60, 90, 120]], [30, 60], id='diagonal-node-slope'),
    pytest.param([[0, 0], [0, 30.000000001]], [30], id='tiny-nonzero-line'),
    pytest.param([[0, 0, 0], [0, 50, 0], [0, 0, 0]], [30], id='closed-pit-ring'),
    pytest.param([[50, 10], [10, 70]], [30], id='saddle-mean-above'),
    pytest.param([[31, 0], [0, 31]], [30], id='saddle-mean-below'),
    pytest.param([[5, 15, 25, 35]] * 2 + [[None] * 4] + [[5, 15, 25, 35]] * 2,
                 [30], id='gap-termination'),
    pytest.param([[0, 0], [0, 0]], [30], id='no-crossings'),
]


def require_extent(result):
    for lines in result.values():
        for line in lines:
            if len(set(line)) < 2:
                raise AssertionError('collapsed contour chain')
            assert all(a != b for a, b in zip(line, line[1:])), 'consecutive duplicate coordinates'


def unfiltered_trace(monkeypatch, grid, levels):
    """Bypass only final coordinate cleanup, leaving the full actual tracer intact."""
    context = monkeypatch.context() if hasattr(dc, '_clean_chain') else nullcontext(None)
    with context as control:
        if control is not None:
            control.setattr(dc, '_clean_chain', list)
        return dc.trace(grid, levels)


@pytest.mark.parametrize('grid', EXTREMA)
def test_exact_level_extrema_emit_no_lines(grid):
    before = deepcopy(grid)
    result = dc.trace(grid, [30])
    require_extent(result)
    assert result == {30: []}
    assert grid == before


@pytest.mark.parametrize('grid,levels', CASES)
def test_real_geometry_and_order_are_preserved(grid, levels, monkeypatch):
    before = deepcopy(grid)
    baseline = unfiltered_trace(monkeypatch, grid, levels)
    # Independent expected normalization of the ORIGINAL coordinate chains.
    expected = {depth: [clean for line in lines
                        if len(set(clean := [point for point, _ in groupby(line)])) >= 2]
                for depth, lines in baseline.items()}
    result = dc.trace(grid, levels)
    assert result == expected
    require_extent(result)
    assert grid == before
    assert dc.trace(grid, list(reversed(levels)) + levels) == result
    assert dc.trace(grid, levels) == result


def test_specific_positive_shapes():
    assert dc.trace([[0, 30, 60]] * 4, [30]) == {
        30: [[(1.0, 0.0), (1.0, 1.0), (1.0, 2.0), (1.0, 3.0)]]}
    tiny = dc.trace([[0, 0], [0, 30.000000001]], [30])[30]
    assert len(tiny) == 1 and len(set(tiny[0])) == 2
    assert max(abs(a - b) for a, b in zip(*tiny[0])) < 1e-9
    ring = dc.trace([[0, 0, 0], [0, 50, 0], [0, 0, 0]], [30])[30]
    assert len(ring) == 1 and len(ring[0]) == 5
    assert ring[0][0] == ring[0][-1] and len(set(ring[0])) == 4
    for saddle in ([[50, 10], [10, 70]], [[31, 0], [0, 31]]):
        assert len(dc.trace(saddle, [30])[30]) == 2
    grid = [[5, 15, 25, 35]] * 2 + [[None] * 4] + [[5, 15, 25, 35]] * 2
    lines = dc.trace(grid, [30])[30]
    assert len(lines) == 2
    assert [sorted(y for _, y in line) for line in lines] == [[0.0, 1.0], [3.0, 4.0]]


def test_duplicate_nodes_are_collapsed_without_reordering(monkeypatch):
    grid = [[0, 30, 60], [30, 60, 90], [60, 90, 120]]
    original = unfiltered_trace(monkeypatch, grid, [60])
    assert any(a == b for line in original[60] for a, b in zip(line, line[1:]))
    require_extent(dc.trace(grid, [60]))


def test_mutation_control(monkeypatch):
    grid, levels = [[0, 30], [30, 0]], [30]
    slope = [[0, 30, 60]] * 4
    before = deepcopy(grid)
    positive = dc.trace(grid, levels)
    require_extent(positive)
    assert positive == {30: []}
    slope_positive = dc.trace(slope, levels)
    with monkeypatch.context() as control:
        # Identity cleanup restores the original unfiltered final return in memory.
        control.setattr(dc, '_clean_chain', list)
        broken = dc.trace(grid, levels)
        assert broken == {30: [[(1.0, 0.0), (1.0, 0.0)], [(0.0, 1.0), (0.0, 1.0)]]}
        with pytest.raises(AssertionError, match='^collapsed contour chain$'):
            require_extent(broken)
        assert dc.trace(slope, levels) == slope_positive
    assert dc.trace(grid, levels) == positive
    assert grid == before

"""Report exact cross-tile shoreline run lineage without changing geometry."""

from collections.abc import Sequence
from typing import TypedDict

Run = Sequence[Sequence[float]]


class LineageReport(TypedDict):
    tiles: tuple[str, str]
    duplicates: list[tuple[int, int]]
    neighbors: list[tuple[int, int]]


def report_lineage(
    first_tile: str, first_runs: Sequence[Run], second_tile: str, second_runs: Sequence[Run],
) -> LineageReport:
    """Compare decoded runs from a caller-supplied pair of adjacent tiles.

    Each run has at least two XY vertices in the same coordinate space (not
    tile-local coordinates). Findings are zero-based run index pairs in the
    order of the reported tile IDs. A duplicate matches every vertex in order
    or in reverse; a neighbor shares exactly one distinct terminal vertex.
    No snapping, intersection testing, or suppressing input runs is performed.
    """
    report: LineageReport = {'tiles': (first_tile, second_tile), 'duplicates': [], 'neighbors': []}
    # Decoded coordinates may be lists; tuple keys preserve their exact values.
    second = [tuple((x, y) for x, y in run) for run in second_runs]
    for i, run in enumerate(first_runs):
        points = tuple((x, y) for x, y in run)
        reverse = points[::-1]
        ends = {points[0], points[-1]}
        for j, other in enumerate(second):
            if other == points or other == reverse:
                report['duplicates'].append((i, j))
            elif len(ends.intersection((other[0], other[-1]))) == 1:
                report['neighbors'].append((i, j))
    return report

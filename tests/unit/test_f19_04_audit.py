"""F19-04 offline contour block controls; no change to the contour producer.

Pytest checks the fixture's reference observations without the survey stack.
Run `python -B -m tests.unit.test_f19_04_audit` with the survey stack to replay
those expectations against the unchanged builder. This read-only receipt exits
1 on a gap and is deliberately not a required check before the repair.
"""

from collections import Counter
from math import isnan
from statistics import mean
from typing import NamedTuple

import pytest

from skippercast.platform import seafloor_ec as ec


class Observation(NamedTuple):
    depth_m: float | None
    owner: int
    provenance: str
    unresolved_reason: str | None = None


class Case(NamedTuple):
    name: str
    second_group: bool
    conflict: bool
    contributors: tuple[int, ...]
    expected: Observation


# A partial 8 m grid overlaps three cells of a complete 8 m grid. A later,
# complete 16 m grid optionally creates a second group at the SAME datum.
# Without that group, the seam policy uses first valid cells and majority
# ownership, with the class/reason of those selected cells. With that group,
# the first complete grid wins, including its cells and all their EC codes.
CASES = (
    Case('same-group-mixed', False, False, (0, 0, 0, 1), Observation(6.5, 0, 'filled')),
    Case('same-group-unresolved', False, True, (0, 0, 0, 1), Observation(None, 0, 'unresolved', 'conflict')),
    Case('across-groups-complete', True, False, (1, 1, 1, 1), Observation(20, 1, 'verified')),
    Case('across-groups-loser-conflict', True, True, (1, 1, 1, 1), Observation(20, 1, 'verified')),
)


def _inputs(case):
    elevations = [(-2, -2, -2, None), (-20,) * 4]
    codes = [
        ('unresolved-conflict' if case.conflict else 'filled-hole', 'measured', 'measured', 'nodata'),
        ('verified',) * 4,
    ]
    if case.second_group:
        elevations.append((-30,))
        codes.append(('measured',))
    return elevations, codes


@pytest.mark.parametrize('case', CASES, ids=[case.name for case in CASES])
def test_reference_cells_support_expected_depth_and_provenance(case):
    # Use the declared contributor plan, not the producer's selection, to
    # verify these expected observations. The opt-in replay checks selection.
    elevations, codes = _inputs(case)
    selected = [codes[owner][cell] for cell, owner in enumerate(case.contributors)]
    depths = [-elevations[owner][cell] for cell, owner in enumerate(case.contributors)]
    provenance = ec.block_class([ec.CODES[code] for code in selected])
    reason = 'conflict' if 'unresolved-conflict' in selected else None
    owner = Counter(case.contributors).most_common(1)[0][0]
    assert Observation(None if reason else mean(depths), owner, provenance, reason) == case.expected


def _replay():
    # GIS is opt-in only; no on-disk rasters, catalogue, or output generation.
    from contextlib import ExitStack
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from scripts import build_depth_contours as builder

    def raster(stack, cells, n, dtype, nodata=None):
        memory = stack.enter_context(MemoryFile())
        with memory.open(driver='GTiff', width=n, height=n, count=1, dtype=dtype,
                         transform=from_origin(0, 16, 16 / n, 16 / n), nodata=nodata) as dataset:
            dataset.write(np.asarray(cells, dtype=dtype).reshape(n, n), 1)
        return stack.enter_context(memory.open())

    classes = {index: name for name, index in builder.CLASS_INDEX.items()}
    gap = False
    for case in CASES:
        elevations, codes = _inputs(case)
        sides = (2, 2, 1)[:len(elevations)]
        with ExitStack() as stack:
            grids = [raster(stack, values, n, 'float32', np.nan) for values, n in zip(elevations, sides)]
            ecs = [[raster(stack, [ec.CODES[c] for c in values], n, 'uint8')] for values, n in zip(codes, sides)]
            blocks = builder.merged_blocks(
                grids, (0, 16, 1, 1), [(0, 0, n) for n in sides], [(n, 'synthetic-datum') for n in sides], ecs)
        assert len(blocks) == 5, 'EC replay must return provenance along with depths and owners'
        depth, owner, cls, reason, _ = blocks
        feet, why = depth.item(), reason.item()
        actual = Observation(None if isnan(feet) else round(feet / builder.dc.FEET_PER_M, 8),
                             owner.item(), classes.get(cls.item(), 'none'),
                             None if why == -1 else ec.UNRESOLVED_REASONS[why])
        mismatched = [field for field in Observation._fields if getattr(actual, field) != getattr(case.expected, field)]
        gap |= bool(mismatched)
        status = 'GAP (' + ', '.join(mismatched) + ')' if mismatched else 'PASS'
        print(f'{case.name}: {status}; expected {tuple(case.expected)}, observed {tuple(actual)}')
    return int(gap)


if __name__ == '__main__':
    raise SystemExit(_replay())

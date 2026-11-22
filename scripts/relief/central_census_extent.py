"""Compare supplied census inventory extents with one Central fishing window.

Bounding boxes are inventory evidence only: neither their union nor the residual
establishes survey coverage, valid depth, or any source's eligibility for use.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from skippercast.relief.select import box_of


@dataclass(frozen=True)
class CensusExtent:
    inventory_extent: BaseGeometry
    inventory_gap: BaseGeometry
    unusable_box_indices: tuple[int, ...]


def compare_extent(fishing_bounds: list[int | float], inventory_rows: Iterable[object]) -> CensusExtent:
    """Compare WGS84 boxes using the same bounds parser as relief selection.

    Pass the fishing window's ``fishing_bounds`` and the census ``files`` rows.
    Geometry stays in lon/lat with no area conversion. Bad inventory boxes are
    reported by zero-based row index; valid disjoint or edge-touching boxes are
    not errors and contribute no area. An invalid window is refused.
    """
    try:
        west, south, east, north = box_of({'bounds': fishing_bounds})
    except (ValueError, OverflowError) as exc:
        raise ValueError('invalid fishing_bounds: expected WGS84 bounds') from exc
    window = box(west, south, east, north)
    clips = []
    unusable = []
    for index, row in enumerate(inventory_rows):
        try:
            bounds = box_of(row)
        except (KeyError, TypeError, ValueError, OverflowError):
            unusable.append(index)
            continue
        clipped = window.intersection(box(*bounds))
        if clipped.area > 0:
            clips.append(clipped)

    extent = unary_union(clips) if clips else Polygon()
    return CensusExtent(extent, window.difference(extent), tuple(unusable))

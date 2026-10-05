"""The ``grid`` aggregate module: events binned into ``resolution_m`` square cells.

A fixed global grid, so a cell's id never depends on which events arrived: rows
are ``resolution_m`` of latitude (``METRES_PER_DEG`` metres per degree), and
within a row columns are ``resolution_m`` of longitude at the row's centre
latitude. That matches how ``server/fleet/map.ts`` draws a cell (a square of
``resolution_m`` centred on the stored point, equirectangular), so the drawn
square is the cell. ``cell_id`` is ``g<resolution_m>:<row>:<col>``.
"""
from __future__ import annotations

import math
from typing import Iterable

from ..events import Event
from ..simplify import METRES_PER_DEG
from .base import AggregateParams, Cell, build_cells, register

__all__ = ["DEFAULT_RESOLUTION_M", "Grid", "GRID", "grid_cell"]

DEFAULT_RESOLUTION_M = 1000.0  # design.md section 3, and map.ts DEFAULT_CELL_M


def grid_cell(lat: float, lon: float, resolution_m: float) -> tuple[str, float, float]:
    """(cell_id, centre lat, centre lon) of the grid cell holding the point."""
    d_lat = resolution_m / METRES_PER_DEG
    row = math.floor(lat / d_lat)
    centre_lat = (row + 0.5) * d_lat
    d_lon = resolution_m / (METRES_PER_DEG * max(math.cos(math.radians(centre_lat)), 0.01))
    col = math.floor(lon / d_lon)
    centre_lon = (col + 0.5) * d_lon
    return f"g{resolution_m:g}:{row}:{col}", centre_lat, centre_lon


class Grid:
    name = "grid"

    def bin(self, event: Event, params: AggregateParams) -> tuple[str, float, float]:
        return grid_cell(event.lat, event.lon, params.resolution_m or DEFAULT_RESOLUTION_M)

    def compute(self, events: Iterable[Event], params: AggregateParams, **options) -> list[Cell]:
        """Cells for ``events`` (``base.build_cells`` options: ``now_ms``, ``tz``, ``computed_at``)."""
        return build_cells(self, events, params, **options)


GRID = register(Grid())

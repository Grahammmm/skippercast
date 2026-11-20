"""RF1940-4: grid cell ids keep the exact configured edge (synthetic positions only)."""
from __future__ import annotations

import math
import re
import unittest

from skippercast.fleet.ais.aggregate.base import AggregateParams
from skippercast.fleet.ais.aggregate.grid import GRID, grid_cell
from skippercast.fleet.ais.simplify import METRES_PER_DEG

DECIMAL = re.compile(r"^g(\d+(?:\.\d+)?):(-?\d+):(-?\d+)$")


def _edge(cell_id: str) -> float:
    match = DECIMAL.match(cell_id)
    assert match, cell_id
    return float(match.group(1))


class GridResolutionTextTests(unittest.TestCase):
    def test_fractional_edges_keep_exact_resolution(self):
        a = grid_cell(0.0, 0.0, 1000.0001)
        b = grid_cell(0.0, 0.0, 1000.0002)
        self.assertNotEqual(a[0], b[0])
        self.assertEqual(_edge(a[0]), 1000.0001)
        self.assertEqual(_edge(b[0]), 1000.0002)
        for cell, edge in ((a, 1000.0001), (b, 1000.0002)):
            d_lat = edge / METRES_PER_DEG
            self.assertEqual(cell[1], 0.5 * d_lat)
            d_lon = edge / (METRES_PER_DEG * max(math.cos(math.radians(cell[1])), 0.01))
            self.assertEqual(cell[2], 0.5 * d_lon)

    def test_edge_text_is_decimal_and_round_trippable(self):
        for edge in (math.nextafter(1000.0, math.inf), 99999.9999, 1.23456789):
            cell_id = grid_cell(10.0, 20.0, edge)[0]
            self.assertEqual(_edge(cell_id), edge, cell_id)

    def test_exact_legacy_identifiers_are_unchanged(self):
        for edge, text in ((1, "1"), (1.5, "1.5"), (1000, "1000"), (3000, "3000"), (11132, "11132")):
            self.assertTrue(grid_cell(0.0, 0.0, edge)[0].startswith(f"g{text}:0:0"), edge)
        self.assertEqual(grid_cell(0.0, 0.0, 1000.0), grid_cell(0.0, 0.0, 1000))
        self.assertEqual(grid_cell(0.0, 0.0, 1000)[0], "g1000:0:0")

    def test_configuration_keeps_fractional_resolution(self):
        params = AggregateParams.from_mapping({"module": "grid", "resolution_m": 1000.0001})
        self.assertEqual(params.resolution_m, 1000.0001)
        event = type("E", (), {"lat": 0.0, "lon": 0.0, "kind": None})()
        self.assertEqual(GRID.bin(event, params), grid_cell(0.0, 0.0, 1000.0001))
        self.assertEqual(_edge(GRID.bin(event, params)[0]), 1000.0001)


if __name__ == "__main__":
    unittest.main()

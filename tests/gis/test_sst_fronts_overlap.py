"""RF1410-8: overlapping SST cells that disagree are refused, never resolved by tile order."""

import json
from pathlib import Path
import tempfile
import unittest

from skippercast.pipeline.sst_fronts import SstFrontError, publish, publish_region
from tests.gis.test_sst_fronts import ERROR, HEALTH, NOW, at, fronts, tile

EDGE = tile(range(12), at(6))
UNIFORM = tile(range(12), at(6), temp=lambda i, j: 15.0)
CONFLICT = "conflicting overlapping measurements"


def one_frame(*tiles):
    """The cells of several tiles pooled into a single frame (a duplicate inside one tile)."""
    cells = [c for t in tiles for c in t["frames"][0]["cells"]]
    return {**tiles[0], "frames": [{"time": tiles[0]["frames"][0]["time"], "cells": cells}]}


def with_cell(base, index, value):
    """A copy of `base` whose first cell has field `index` replaced by `value`."""
    cells = [list(c) for c in base["frames"][0]["cells"]]
    cells[0][index] = value
    return {**base, "frames": [{"time": base["frames"][0]["time"], "cells": cells}]}


class OverlapTests(unittest.TestCase):
    def test_conflicting_temperature_refuses_in_both_orders(self):
        for label, tiles in (("edge first", (EDGE, UNIFORM)), ("uniform first", (UNIFORM, EDGE)), ("one frame", (one_frame(EDGE, UNIFORM),))):
            with self.subTest(label):
                with self.assertRaisesRegex(SstFrontError, CONFLICT):
                    fronts(*tiles)

    def test_conflicting_error_or_latitude_basis_refuses(self):
        # 35.0 and 35.001 both round to grid row 3500 at 0.01 degrees: the same address, a different latitude basis.
        self.assertEqual(round(35.0 / 0.01), round(35.001 / 0.01))
        for label, changed in (("analysis error", with_cell(EDGE, 3, ERROR + 0.1)), ("latitude", with_cell(EDGE, 0, 35.001))):
            for order in ((EDGE, changed), (changed, EDGE)):
                with self.subTest(label, first=order[0] is EDGE):
                    with self.assertRaisesRegex(SstFrontError, CONFLICT):
                        fronts(*order)

    def test_identical_overlap_is_idempotent(self):
        control = fronts(EDGE)
        self.assertEqual(len(control["fronts"]), 1)
        self.assertEqual(fronts(EDGE, EDGE), control)
        self.assertEqual(fronts(one_frame(EDGE, EDGE)), control)

    def test_missing_cells_do_not_erase_a_valid_cell(self):
        control = fronts(EDGE)
        blank = with_cell(EDGE, 2, None)  # first cell has no temperature: not judged
        blank_error = with_cell(EDGE, 3, None)
        for other in (blank, blank_error):
            self.assertEqual(fronts(EDGE, other), control)
            self.assertEqual(fronts(other, EDGE), control)

    def test_older_conflict_does_not_poison_the_newest_observation(self):
        older = tile(range(12), at(30), temp=lambda i, j: 15.0)
        control = fronts(EDGE)
        self.assertEqual(fronts(older, EDGE), control)
        self.assertEqual(fronts(EDGE, older), control)

    def test_publish_region_refusal_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory:
            region = Path(directory) / "test-coast"
            (region / "habitat-tiles").mkdir(parents=True)
            (region / "habitat-tiles" / "sst-analysis-a.json").write_text(json.dumps(EDGE))
            (region / "habitat-tiles" / "sst-analysis-b.json").write_text(json.dumps(UNIFORM))
            health = Path(directory) / "feed-health.json"
            health.write_text(json.dumps(HEALTH))
            sentinel = b'{"sentinel": "previous output"}\n'
            (region / "sst-fronts.json").write_bytes(sentinel)
            with self.assertRaisesRegex(SstFrontError, CONFLICT):
                publish_region(region, health, NOW)
            self.assertEqual((region / "sst-fronts.json").read_bytes(), sentinel)
            self.assertEqual(sorted(p.name for p in region.iterdir()), ["habitat-tiles", "sst-fronts.json"])


if __name__ == "__main__":
    unittest.main()

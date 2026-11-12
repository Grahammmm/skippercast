"""RF0640-8: time-eligible SST frames with malformed cells are refused by name, never skipped or an IndexError."""

import json
from pathlib import Path
import tempfile
import unittest

from skippercast.pipeline.sst_fronts import SstFrontError, publish_region
from tests.gis.test_sst_fronts import FIELDS, HEALTH, NOW, at, fronts, tile

EDGE = tile(range(12), at(6))
NEWEST = at(1)
MISSING = object()


def with_cells(base, cells, time=None):
    frame = {"time": base["frames"][0]["time"] if time is None else time}
    if cells is not MISSING:
        frame["cells"] = cells
    return {**base, "frames": [frame]}


def good_cells(time=NEWEST):
    return tile(range(12), time)["frames"][0]["cells"]


class CellsTests(unittest.TestCase):
    def test_current_cells_container_refuses(self):
        for label, bad in (("missing", MISSING), ("null", None), ("scalar", 7), ("string", "SECRET-PAYLOAD"), ("mapping", {"SECRET-PAYLOAD": 1})):
            with self.subTest(label):
                with self.assertRaises(SstFrontError) as caught:
                    fronts(with_cells(EDGE, bad, NEWEST))
                self.assertIn("t0 frame 0", str(caught.exception))
                self.assertNotIn("SECRET-PAYLOAD", str(caught.exception))

    def test_current_cell_row_shape_refuses(self):
        good = good_cells()
        for label, bad in (("null", None), ("scalar", 3), ("string", "SECRET-PAYLOAD"), ("mapping", {"SECRET-PAYLOAD": 1}), ("short", good[0][:3])):
            with self.subTest(label):
                with self.assertRaises(SstFrontError) as caught:
                    fronts(with_cells(EDGE, [good[0], bad], NEWEST))
                self.assertIn("t0 frame 0: cell 1", str(caught.exception))
                self.assertNotIn("SECRET-PAYLOAD", str(caught.exception))

    def test_malformed_newest_does_not_fall_back(self):
        broken = with_cells(EDGE, MISSING, NEWEST)
        for order in ((EDGE, broken), (broken, EDGE)):
            with self.assertRaises(SstFrontError):
                fronts(*order)

    def test_empty_current_array_is_legitimate(self):
        doc = fronts(EDGE, with_cells(EDGE, [], NEWEST))
        self.assertEqual(doc["observed_at"], "2026-11-03T11:00:00Z")
        self.assertEqual(doc["fronts"], [])

    def test_extra_columns_and_reordered_fields_are_accepted(self):
        control = fronts(EDGE)
        order = [3, 2, 1, 0, 4, 5]
        reordered = {**EDGE, "fields": [FIELDS[k] for k in order],
                     "frames": [{"time": EDGE["frames"][0]["time"], "cells": [[c[k] for k in order] + ["extra"] for c in EDGE["frames"][0]["cells"]]}]}
        self.assertEqual(fronts(reordered), control)
        trimmed = {**EDGE, "frames": [{"time": EDGE["frames"][0]["time"], "cells": [c[:4] for c in EDGE["frames"][0]["cells"]]}]}
        self.assertEqual(fronts(trimmed), control)

    def test_time_refusal_precedes_cell_validation(self):
        for label, time, key in (("missing", MISSING, "missing_time"), ("unparseable", "yesterday-ish", "unparseable_time"),
                                 ("future", at(-1), "future"), ("stale", at(49), "stale")):
            with self.subTest(label):
                frame = {} if time is MISSING else {"time": time}
                doc = fronts({**EDGE, "frames": [{**frame, "cells": "bad"}]})
                self.assertEqual(doc["refused_frames"][key], 1)
                self.assertEqual(doc["fronts"], [])
        with self.assertRaises(SstFrontError):  # an eligible older frame is still checked
            fronts(EDGE, with_cells(EDGE, [None], at(30)))

    def test_refusal_preserves_prior_local_document(self):
        with tempfile.TemporaryDirectory() as directory:
            region = Path(directory) / "test-coast"
            (region / "habitat-tiles").mkdir(parents=True)
            (region / "habitat-tiles" / "sst-analysis-a.json").write_text(json.dumps(EDGE))
            (region / "habitat-tiles" / "sst-analysis-b.json").write_text(json.dumps(with_cells(EDGE, [good_cells()[0], [1]], NEWEST)))
            health = Path(directory) / "feed-health.json"
            health.write_text(json.dumps(HEALTH))
            sentinel = b'{"sentinel": "previous output"}\n'
            (region / "sst-fronts.json").write_bytes(sentinel)
            with self.assertRaises(SstFrontError):
                publish_region(region, health, NOW)
            self.assertEqual((region / "sst-fronts.json").read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()

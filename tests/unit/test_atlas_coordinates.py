"""Oversized integer atlas coordinates are ordinary WGS84 refusals, not OverflowError."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from skippercast.atlas.export import coordinate, main, validate, write_exports
from tests._support import ROOT

DATA = ROOT / "atlas/avila-point-estero-2026-09-20/data/atlas.json"
HUGE = 10 ** 400
BOUNDS = "Coordinate outside WGS84 bounds"


class OversizedCoordinates(unittest.TestCase):
    base = json.loads(DATA.read_text(encoding="utf-8"))

    def bad(self, where):
        data = copy.deepcopy(self.base)
        where(data)
        return data

    def cases(self):
        for sign in (HUGE, -HUGE):
            yield "target lon", self.bad(lambda d: d["targets"][0].update(longitude=sign))
            yield "target lat", self.bad(lambda d: d["targets"][0].update(latitude=sign))
            yield "ring", self.bad(lambda d: d["areas"][0]["geometry"]["coordinates"][0].__setitem__(
                1, [sign, 35.0]))
            yield "drift", self.bad(lambda d: d["drifts"][0]["geometry"]["coordinates"].__setitem__(
                1, [-120.0, sign]))

    def test_direct_both_axes_and_signs_refuse_as_bounds(self):
        for value in (HUGE, -HUGE):
            for pos in ([value, 0], [0, value], (value, 0), (0, value)):
                with self.assertRaisesRegex(ValueError, BOUNDS):
                    coordinate(pos)

    def test_target_polygon_and_drift_share_gate(self):
        for label, data in self.cases():
            with self.subTest(label), self.assertRaisesRegex(ValueError, BOUNDS):
                validate(data)

    def test_cli_actions_exit_1_with_normal_diagnostic_and_write_nothing(self):
        for label, data in self.cases():
            for action in ("validate", "export"):
                with self.subTest(label, action=action), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    src = root / "atlas.json"
                    src.write_text(json.dumps(data), encoding="utf-8")
                    sentinel = root / "sibling.txt"
                    sentinel.write_bytes(b"keep")
                    out, err = io.StringIO(), io.StringIO()
                    args = [action, "--data", str(src)]
                    if action == "export":
                        args += ["--output", str(root / "a" / "b" / "out")]
                    with redirect_stdout(out), redirect_stderr(err), \
                            self.assertRaises(SystemExit) as caught:
                        main(args)
                    self.assertEqual(caught.exception.code, 1)
                    self.assertTrue(err.getvalue().startswith(f"Atlas operation failed: {BOUNDS}"))
                    self.assertEqual(out.getvalue(), "")
                    self.assertFalse((root / "a").exists())
                    self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_write_exports_does_not_prepare_output(self):
        data = next(self.cases())[1]
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "a" / "out"
            with self.assertRaisesRegex(ValueError, BOUNDS):
                write_exports(data, out)
            self.assertFalse((Path(tmp) / "a").exists())

    def test_accepted_edges_and_ordinary_refusals_unchanged(self):
        for pos in ([-180, -90], [180, 90], [0, 0], (0.0, 0.0), [-120.5, 35.2],
                    [-180.0, -90.0], [180.0, 90.0]):
            before = copy.deepcopy(pos)
            self.assertIsNone(coordinate(pos))
            self.assertEqual(pos, before)
        for pos in ([181, 0], [0, 91], [-180.5, 0], [0, -90.5], [0, 91.0]):
            with self.assertRaisesRegex(ValueError, BOUNDS):
                coordinate(pos)

    def test_invalid_types_and_nonfinite_keep_diagnostics(self):
        for pos in ([True, 0], [0, False], ["1", 0], [None, 0], [float("nan"), 0],
                    [0, float("inf")], [float("-inf"), 0]):
            with self.assertRaisesRegex(ValueError, "Invalid coordinate"):
                coordinate(pos)
        for pos in ([0], [0, 0, 0], "ab", {"a": 1, "b": 2}, None):
            with self.assertRaisesRegex(ValueError, "must be \\[longitude, latitude\\]"):
                coordinate(pos)


if __name__ == "__main__":
    unittest.main()

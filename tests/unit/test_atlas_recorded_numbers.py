"""Boolean and nonfinite recorded atlas measurements are refused, not admitted as evidence."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from skippercast.atlas import export
from skippercast.atlas.export import main, validate, write_exports
from tests._support import ROOT

DATA = ROOT / "atlas/avila-point-estero-2026-09-20/data/atlas.json"
INVALID = "Invalid recorded numeric evidence"
INF = float("inf")
TARGET_KEYS = ("native_center_depth_ft", "native_100m_circle_min_depth_ft",
               "native_100m_circle_max_depth_ft")
GEOMETRY_KEYS = ("minimum_ft", "maximum_ft", "closure_clearance_m")


class RecordedNumbers(unittest.TestCase):
    base = json.loads(DATA.read_text(encoding="utf-8"))

    def make(self, section, key, value, index=0):
        data = copy.deepcopy(self.base)
        data[section][index]["recorded_validation"][key] = value
        return data

    def cases(self, values):
        for key in TARGET_KEYS:
            for value in values:
                yield f"targets/{key}", self.make("targets", key, value)
        for section in ("areas", "drifts"):
            for key in GEOMETRY_KEYS:
                for value in values:
                    # a late row, so valid siblings come first
                    yield f"{section}/{key}", self.make(section, key, value, -1)

    def test_recorded_depths_reject_boolean_measurements(self):
        for value in (True, False):
            for label, data in self.cases((value,)):
                with self.subTest(label, value=value), self.assertRaisesRegex(ValueError, INVALID):
                    validate(data)
        for section in ("areas", "drifts"):
            data = copy.deepcopy(self.base)
            check = data[section][0]["recorded_validation"]
            check["minimum_ft"] = check["maximum_ft"] = True
            with self.subTest(section), self.assertRaisesRegex(ValueError, INVALID):
                validate(data)

    def test_recorded_measurements_reject_wrong_types_and_nonfinite(self):
        values = (None, "12", [12], {"v": 12}, float("nan"), INF, -INF)
        for label, data in self.cases(values):
            before = copy.deepcopy(data)
            with self.subTest(label), self.assertRaisesRegex(ValueError, f"^{INVALID}$"):
                validate(data)
            self.assertEqual(data, before)

    def test_clearance_infinity_is_not_recorded_evidence(self):
        for section in ("areas", "drifts"):
            with self.assertRaisesRegex(ValueError, INVALID):
                validate(self.make(section, "closure_clearance_m", INF))
            for ok in (500, 500.0, 10 ** 400):
                validate(self.make(section, "closure_clearance_m", ok))

    def test_cli_refusal_precedes_output_preparation(self):
        bad = {
            "true depth": self.make("targets", "native_center_depth_ft", True),
            "inf clearance": self.make("areas", "closure_clearance_m", INF),
        }
        for label, data in bad.items():
            for action in ("validate", "export"):
                with self.subTest(label, action=action), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    src = root / "atlas.json"
                    src.write_text(json.dumps(data), encoding="utf-8")  # Infinity literal
                    sibling = root / "sibling.txt"
                    sibling.write_bytes(b"keep")
                    args = [action, "--data", str(src)]
                    if action == "export":
                        args += ["--output", str(root / "a" / "out")]
                    out, err = io.StringIO(), io.StringIO()
                    with redirect_stdout(out), redirect_stderr(err), \
                            self.assertRaises(SystemExit) as caught:
                        main(args)
                    self.assertEqual(caught.exception.code, 1)
                    self.assertEqual(err.getvalue(), f"Atlas operation failed: {INVALID}\n")
                    self.assertEqual(out.getvalue(), "")
                    self.assertFalse((root / "a").exists())
                    self.assertEqual(sibling.read_bytes(), b"keep")
        with TemporaryDirectory() as tmp, \
                mock.patch.object(export.tempfile, "mkdtemp") as mkdtemp:
            with self.assertRaisesRegex(ValueError, INVALID):
                write_exports(bad["true depth"], Path(tmp) / "a" / "out")
            mkdtemp.assert_not_called()
            self.assertFalse((Path(tmp) / "a").exists())

    def test_valid_measurements_and_range_boundaries_stay_compatible(self):
        summary = validate(copy.deepcopy(self.base))
        self.assertEqual(summary["targets"], len(self.base["targets"]))
        validate(self.make("targets", "native_center_depth_ft", 200))
        validate(self.make("targets", "native_center_depth_ft", 0.5))
        for section in ("areas", "drifts"):
            validate(self.make(section, "maximum_ft", 195))
        ranges = (
            ("targets", "native_center_depth_ft", 0, "source-depth ceiling"),
            ("targets", "native_center_depth_ft", 201, "source-depth ceiling"),
            ("targets", "native_center_depth_ft", 10 ** 400, "source-depth ceiling"),
            ("areas", "maximum_ft", 196, "conservative source-depth"),
            ("areas", "closure_clearance_m", 499.9, "closure planning margin"),
            ("drifts", "closure_clearance_m", 499, "closure planning margin"),
        )
        for section, key, value, message in ranges:
            with self.subTest(section=section, key=key, value=value), \
                    self.assertRaisesRegex(ValueError, message):
                validate(self.make(section, key, value))


if __name__ == "__main__":
    unittest.main()

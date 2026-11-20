import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research.scripts import audit_cal_dig_shallow_300_gap as audit


def table(kind, *depths):
    label = "concept" if kind == "biotic" else "Induration"
    header = f"depth_mete,Longitude,Latitude,video_sequ,{label}\n"
    return header + "".join(f"{depth},0,0,synthetic,example\n" for depth in depths)


def reject_nonfinite_json(token):
    raise ValueError(f"Nonfinite JSON constant: {token}")


class CalDigNonfiniteDepthTest(unittest.TestCase):
    def run_audit(self, output, biotic, substrate):
        biotic_path = output.parent / "biotic.csv"
        substrate_path = output.parent / "substrate.csv"
        biotic_path.write_text(table("biotic", *biotic))
        substrate_path.write_text(table("substrate", *substrate))
        args = ["audit", "--biotic", str(biotic_path), "--substrate", str(substrate_path),
                "--output", str(output)]
        with patch.object(sys, "argv", args):
            audit.main()

    def test_all_invalid_depths_do_not_write_gap_receipt(self):
        for depth in ("NaN", "inf", "-inf", "1e999"):
            with self.subTest(depth=depth), TemporaryDirectory() as tmp:
                output = Path(tmp) / "gap.json"
                with self.assertRaisesRegex(ValueError, "observations missing"):
                    self.run_audit(output, [depth, "", "-10"], ["110"])
                self.assertFalse(output.exists())

    def test_finite_depth_supports_gap_without_counting_nonfinite_rows(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "gap.json"
            self.run_audit(output, ["NaN", "inf", "-inf", "110"], ["110"])
            sources = json.loads(output.read_text(), parse_constant=reject_nonfinite_json)["sources"]
        biotic = sources["biotic"]
        self.assertEqual(biotic["nonfinite_depth_rows_excluded"], 3)
        self.assertEqual(biotic["negative_depth_rows_excluded"], 0)
        for source in sources.values():
            self.assertEqual(source["minimum_nonnegative_observation_depth_m"], 110)
            self.assertEqual(source["maximum_nonnegative_observation_depth_m"], 110)
            self.assertEqual(source["observations_in_200_300ft_depth_band"], 0)

    def test_writer_rejects_nonfinite_report_values(self):
        # Protect the serialization boundary even if a future field bypasses the depth filter.
        with TemporaryDirectory() as tmp, patch.object(audit, "build", return_value={"value": float("nan")}):
            output = Path(tmp) / "gap.json"
            with self.assertRaises(ValueError):
                self.run_audit(output, ["110"], ["110"])
            self.assertFalse(output.exists())

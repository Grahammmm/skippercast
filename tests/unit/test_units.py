"""RF0708-1: skippercast.util.units is the one ft/m source for the offline BAG code."""
import ast
from pathlib import Path
import unittest.mock

from skippercast.fleet.ais import match
from skippercast.util import units

SRC = Path(__file__).resolve().parents[2] / "src" / "skippercast"
BAG = [SRC / "coastal/authenticated_v1/adapter_bag.py", SRC / "seafloor/adapters/regular_bag_window.py"]
LENGTHS = [float(n) for n in range(1, 1024)] + [n / 10 for n in range(10, 1201)]

def verdict(length_m, ratio, ft_per_m):  # registry length_ft set exactly (ratio - 1) off the AIS length
    return match._Vessel({"id": "v", "length_ft": length_m * ft_per_m / ratio}).length_check(match.Static(1, 0, "ais", length_m=length_m))


class UnitsTests(unittest.TestCase):
    def test_constants_are_exact_and_import_nothing(self):
        self.assertEqual(units.M_PER_FT, 0.3048)
        self.assertAlmostEqual(units.FT_PER_M * units.M_PER_FT, 1.0, delta=1e-15)
        self.assertAlmostEqual(units.KT_PER_MS, 1.9438444924406, delta=1e-12)
        tree = ast.parse((SRC / "util/units.py").read_text(encoding="utf-8"))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])

    def test_bag_depth_band_is_byte_identical(self):
        for path in BAG:
            body = ast.parse(path.read_text(encoding="utf-8")).body
            names = {t.id: n.value for n in body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
            self.assertNotIn("METERS_PER_FOOT", names, path)  # no local spelling left to drift
            self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == "skippercast.util.units"
                                and [(a.name, a.asname) for a in n.names] == [("M_PER_FT", "METERS_PER_FOOT")]
                                for n in body), path)
            for key in ("MINIMUM_DEPTH_FT", "MAXIMUM_DEPTH_FT"):
                self.assertEqual((feet := ast.literal_eval(names[key])) * units.M_PER_FT, feet * 0.3048, (path, key))

    def test_ais_rounding_holds_but_tolerance_boundary_flips_so_match_keeps_its_literal(self):
        self.assertEqual([L for L in LENGTHS if round(L * units.FT_PER_M, 1) != round(L * 3.28084, 1)], [])
        self.assertEqual(match.FT_PER_M, 3.28084)  # spec Design: a changed verdict keeps the literal
        for L in LENGTHS:
            for ratio in (1.2, 0.8, 1.2001, 0.7999):  # exactly 20% off either way, then just past it
                ft = L * 3.28084 / ratio  # main's length_check, written out
                self.assertEqual(verdict(L, ratio, 3.28084), "agrees" if abs(L * 3.28084 - ft) <= 0.2 * ft else "contradicts")
                self.assertTrue(ratio in (1.2, 0.8) or verdict(L, ratio, 3.28084) == "contradicts", (L, ratio))
        with unittest.mock.patch.object(match, "FT_PER_M", units.FT_PER_M):  # main: 1 m at 1.2 "agrees" (loop above)
            self.assertEqual(verdict(1.0, 1.2, units.FT_PER_M), "contradicts")  # 1/0.3048 would flip it

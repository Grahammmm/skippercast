"""RF2135-7: the ocean vector m/s-to-knots factor derives from util.units at the historical eight-decimal precision."""
import ast
import math
import tempfile
import unittest
from pathlib import Path

from skippercast.pipeline import ocean
from skippercast.util.units import KT_PER_MS, M_PER_NMI
from tests._support import ROOT
from tests.unit.test_units_guard import ALLOW, scan

SOURCE = ROOT / "src" / "skippercast" / "pipeline" / "ocean.py"
LEGACY = 1.94384449  # the historical feed factor, spelled independently of the code under test


def legacy(u, v):  # the pre-RF2135-7 formula, copied verbatim with its literal
    if not all(math.isfinite(x) for x in (u, v)) or max(abs(u), abs(v)) > 5:
        return None
    return round(math.hypot(u, v) * LEGACY, 3), round(math.degrees(math.atan2(u, v)) % 360, 1)


def same(a, b):  # tuple equality that also tells -0.0 from 0.0
    return a == b and (a is None or [math.copysign(1, x) for x in a] == [math.copysign(1, x) for x in b])


class OceanUnitsTests(unittest.TestCase):
    def test_vector_shared_factor_without_literal(self):
        text = SOURCE.read_text()
        tree = ast.parse(text)
        imported = [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                    and n.module == "util.units" and n.level == 2 for a in n.names]
        self.assertIn("KT_PER_MS", imported)
        self.assertNotIn("1.94384449", text, "old independent conversion literal still present")
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "vector")
        self.assertIn("_VECTOR_KT_PER_MS", {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)})
        self.assertNotIn("pipeline/ocean.py", ALLOW)
        self.assertEqual(scan(ROOT / "src" / "skippercast"), [])

    def test_vector_exact_historical_factor(self):
        self.assertEqual(ocean._VECTOR_KT_PER_MS, round(KT_PER_MS, 8))
        self.assertEqual(ocean._VECTOR_KT_PER_MS, LEGACY)
        self.assertEqual((KT_PER_MS, M_PER_NMI), (3600 / 1852.0, 1852.0))  # shared owner unchanged

    def test_vector_legacy_grid_and_round_boundaries(self):
        values = [x / 100 for x in range(-500, 501, 7)] + [0.0, -0.0, 5.0, -5.0, 4.999999, 1e-9, -1e-9, 1e-300]
        for u in values:
            for v in values:
                self.assertTrue(same(ocean.vector(u, v), legacy(u, v)), (u, v))
        # speeds straddling each three-decimal half step, one ulp either side
        for k in range(1, 400):
            edge = (k + 0.5) / 1000 / LEGACY
            for s in (math.nextafter(edge, 0), edge, math.nextafter(edge, 9)):
                self.assertTrue(same(ocean.vector(s, 0.0), legacy(s, 0.0)), s)
                self.assertTrue(same(ocean.vector(0.0, -s), legacy(0.0, -s)), s)
        self.assertEqual(ocean.vector(1, 0), (1.944, 90.0))   # toward-bearing: east is 90
        self.assertEqual(ocean.vector(0, -1), (1.944, 180.0))  # south is 180

    def test_vector_refusal_unchanged(self):
        nan, inf = float("nan"), float("inf")
        for bad in (nan, inf, -inf, 5.000001, -5.000001):
            self.assertIsNone(ocean.vector(bad, 0.0), bad)
            self.assertIsNone(ocean.vector(0.0, bad), bad)
        for edge in ((5.0, 5.0), (-5.0, 5.0), (5.0, -5.0), (-5.0, -5.0)):  # |speed| > 5 yet accepted
            self.assertIsNotNone(ocean.vector(*edge))
            self.assertTrue(same(ocean.vector(*edge), legacy(*edge)))

    def test_vector_guard_reintroduced_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "pipeline" / "ocean.py"
            f.parent.mkdir()
            f.write_text("x = 1\nkt = hypot * 1.94384449\n")
            self.assertEqual(scan(Path(tmp), {}), [
                "pipeline/ocean.py:2: ft/m/kt/nmi literal outside util/units.py; import it from skippercast.util.units"])


if __name__ == "__main__":
    unittest.main()

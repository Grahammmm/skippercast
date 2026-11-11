"""RF2345-8: wind intelligence takes its knot factor from skippercast.util.units, values unchanged."""
import ast
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skippercast.util import units
from tests._support import ROOT
from tests.unit.test_units_guard import ALLOW, scan

SOURCE = ROOT / "src/skippercast/pipeline/intelligence.py"
CYCLE, LEGACY = 1790467200, 3600 / 1852


def legacy(v):  # independent expectation: never the imported factor under test
    return round(v * LEGACY, 1)


class IntelligenceFactorOwnerTests(unittest.TestCase):
    def test_alias_is_shared_owner(self):
        from skippercast.pipeline import intelligence
        self.assertIs(intelligence.KNOTS_PER_MS, units.KT_PER_MS)
        self.assertEqual(intelligence.KNOTS_PER_MS, LEGACY)
        tree = ast.parse(SOURCE.read_text())
        imports = [(n.module, a.name, a.asname) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
        self.assertIn(("util.units", "KT_PER_MS", "KNOTS_PER_MS"), imports)
        assigned = [t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        self.assertNotIn("KNOTS_PER_MS", assigned)

    def test_old_expression_is_not_exempt(self):
        self.assertNotIn("pipeline/intelligence.py", ALLOW)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipeline/intelligence.py"
            path.parent.mkdir()
            path.write_text("import os\nKNOTS_PER_MS=3600/1852\n")
            self.assertEqual(scan(Path(tmp), {}), [
                "pipeline/intelligence.py:2: ft/m/kt/nmi literal outside util/units.py; import it from skippercast.util.units"])


class EnsembleConversionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"SKIPPERCAST_FORECAST_ROOT": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        half = 1.95 / LEGACY  # m/s whose knot value sits on a one-decimal half-step
        self.winds = [[0, 3, 6]] * 31
        self.winds = [list(w) for w in self.winds]
        self.winds[1] = [2, None, 2]  # missing native neighbour: excluded at 1 h, endpoints stay valid
        self.winds[2] = [math.nextafter(half, 0), half, math.nextafter(half, 9)]
        self.winds[3] = [-1, 3, 6]  # negative wind omitted
        self.winds[4] = [float("nan"), 3, 6]  # nonfinite native value omitted
        self.winds[5] = [3, 3, 6]  # positive wind with the zero gust below
        self.gusts = [[1, 5, 8]] * 31
        self.gusts = [list(g) for g in self.gusts]
        self.gusts[5] = [0, 0, 0]  # below wind: dropped
        self.gusts[6] = [None, 5, float("inf")]  # missing/nonfinite gust absent
        times = [CYCLE + h * 3600 for h in (0, 3, 6)]
        self.region = {"id": "r", "forecast_points": [{"id": "a", "latitude": 35.5, "longitude": -121.5},
                                                      {"id": "b", "latitude": 35.0, "longitude": -121.0}],
                       "intelligence": {"wind_ensemble_model": "gfs025"}}
        self.write("manifest.json", {"model": "ncep_gefs025", "sea_radius_km": 30, "meta": {
            "last_run_initialisation_time": CYCLE, "last_run_modification_time": CYCLE + 5 * 3600, "data_end_time": times[-1]},
            "upstream": {"cycle_prefix": "https://noaa-gefs-pds.s3.amazonaws.com/x/", "messages": 1, "messages_sha256": "0" * 64, "missing": []}})
        none = [[None] * 3 for _ in range(31)]
        self.write("regions/r.json", {"cycle": CYCLE, "times": times, "members": 31, "units": {"wind_speed_10m": "m/s", "wind_gusts_10m": "m/s"},
                                      "points": [{"latitude": 35.5, "longitude": -121.5, "grid": [35.5, -121.5], "distance_km": 0.0,
                                                  "wind_speed_10m": self.winds, "wind_gusts_10m": self.gusts},
                                                 {"latitude": 35.0, "longitude": -121.0, "grid": None, "distance_km": None,
                                                  "wind_speed_10m": none, "wind_gusts_10m": none}]})

    def write(self, rel, value):
        path = self.root / "ncep_gefs025" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    class Offline:
        def __init__(self):
            self.requests = []

        def get(self, *a, **k):
            raise AssertionError("local build must be read without the network")

    @staticmethod
    def interp(series, h):  # legacy-rule value at hour h of the 0/3/6 h series; None if a neighbour is missing
        if h % 3 == 0:
            v = series[h // 3]
            return v if isinstance(v, (int, float)) and math.isfinite(v) else None
        a, b = series[h // 3], series[h // 3 + 1]
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (a, b)):
            return None
        return a + (b - a) * (h % 3) / 3

    def expected(self, h):
        rows = []
        for m in range(31):
            wind, gust = self.interp(self.winds[m], h), self.interp(self.gusts[m], h)
            if wind is None or wind < 0:
                continue
            wind, gust = legacy(wind), None if gust is None else legacy(gust)
            rows.append([m, wind, gust if gust is not None and gust >= wind else None])
        return rows

    def test_ensemble_conversion_rounding_is_unchanged(self):
        from skippercast.pipeline.intelligence import ensemble
        data = ensemble(self.Offline(), self.region)
        point, unsampled = data["points"]
        self.assertEqual([f["time"] for f in point["frames"]], [CYCLE + h * 3600 for h in range(7)])
        for h, frame in enumerate(point["frames"]):
            self.assertEqual(frame["members"], self.expected(h), f"hour {h}")
        first = dict((m[0], m[1:]) for m in point["frames"][0]["members"])
        self.assertEqual(first[0], [0.0, 1.9])  # zero wind stays zero
        # the three neighbouring half-step inputs round exactly as the legacy ratio rounds them
        self.assertEqual(first[2][0], legacy(self.winds[2][0]))
        self.assertEqual((data["model"], data["expected_members"], data["issued_at"]), ("ncep_gefs025", 31, "2026-09-27T00:00:00Z"))
        self.assertEqual(unsampled["frames"], [])
        self.assertEqual((point["point_id"], point["grid"]), ("a", [35.5, -121.5]))

    def test_ensemble_missing_and_interpolation_are_unchanged(self):
        from skippercast.pipeline.intelligence import ensemble
        frames = ensemble(self.Offline(), self.region)["points"][0]["frames"]
        by = lambda h: dict((m[0], m[1:]) for m in frames[h]["members"])  # noqa: E731
        self.assertNotIn(1, by(1))  # missing native neighbour excludes the member
        self.assertIn(1, by(0))  # a valid native endpoint stays eligible
        self.assertNotIn(3, by(0))  # negative wind omitted
        self.assertNotIn(4, by(0))  # nonfinite wind omitted
        self.assertIsNone(by(0)[5][1])  # gust below wind absent
        self.assertIsNone(by(0)[6][1])  # missing gust absent
        self.assertEqual(by(1)[0], [legacy(1), legacy(1 + 4 / 3)])  # linear interpolation inside the 0->3 h step

    def test_ensemble_admission_is_unchanged(self):
        from skippercast.pipeline.intelligence import ensemble
        moved = {**self.region, "forecast_points": [{**self.region["forecast_points"][0], "latitude": 35.6}, self.region["forecast_points"][1]]}
        with self.assertRaisesRegex(ValueError, "point mismatch"):
            ensemble(self.Offline(), moved)


if __name__ == "__main__":
    unittest.main()

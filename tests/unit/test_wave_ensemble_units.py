"""RF2135-8: the GEFS wave threshold feet derive from util.units at the historical five-decimal factor."""
import ast
import importlib.util

try:
    import numpy  # noqa: F401  (loaded before sys.modules is patched, so it is not unloaded)
except ImportError:
    numpy = None
import sys
import types
import unittest
from unittest.mock import patch

from skippercast.pipeline import wave_ensemble
from skippercast.util.units import FT_PER_M
from tests._support import ROOT
from tests.unit.test_units_guard import ALLOW, scan

SOURCE = ROOT / "src" / "skippercast" / "pipeline" / "wave_ensemble.py"


class FakeCodes(types.ModuleType):
    """Deterministic ecCodes stand-in: each message is a dict of keys; handles are list indexes."""

    def __init__(self, messages):
        super().__init__("eccodes")
        self.messages, self.cursor, self.released = messages, 0, []

    def codes_grib_new_from_file(self, _file):
        if self.cursor >= len(self.messages):
            return None
        self.cursor += 1
        return self.cursor - 1

    def codes_get(self, gid, key):
        return self.messages[gid][key]

    def codes_get_array(self, gid, key):
        import numpy as np
        return np.array(self.messages[gid][key], dtype=float)

    def codes_release(self, gid):
        self.released.append(gid)


def message(scaled, factor, **over):
    base = {"discipline": 10, "parameterCategory": 0, "parameterNumber": 3, "probabilityType": 1,
            "scaledValueOfUpperLimit": scaled, "scaleFactorOfUpperLimit": factor,
            "dataDate": 20261109, "dataTime": 0, "validityDate": 20261109, "validityTime": 300,
            "latitudes": [35.0, 35.25], "longitudes": [-121.0, -121.25], "values": [0.5, 0.25]}
    base.update(over)
    return base


def decode(messages, points):
    fake = FakeCodes(messages)
    with patch.dict(sys.modules, {"eccodes": fake}):
        return wave_ensemble.decode_probabilities(b"GRIB-fake", points), fake


POINT = [{"id": "p", "latitude": 35.0, "longitude": -121.0}]


class WaveEnsembleUnitsTests(unittest.TestCase):
    def test_wave_threshold_shared_factor_no_literal(self):
        tree = ast.parse(SOURCE.read_text())
        imported = [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                    and n.module == "util.units" and n.level == 2 for a in n.names]
        self.assertIn("FT_PER_M", imported)
        self.assertFalse("3.28084" in SOURCE.read_text(), "old independent conversion literal still present")
        self.assertNotIn("pipeline/wave_ensemble.py", ALLOW)
        self.assertEqual(scan(ROOT / "src" / "skippercast"), [])

    def test_wave_threshold_exact_historical_factor(self):
        self.assertEqual(wave_ensemble._THRESHOLD_FT_PER_M, round(FT_PER_M, 5))
        self.assertEqual(wave_ensemble._THRESHOLD_FT_PER_M, 3.28084)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy not installed")
    def test_wave_threshold_decoder_precision_matrix(self):
        cases = [(0, 0), (1, 0), (3, 0), (5, 1), (25, 1), (10, 1), (1, 2), (75, -1), (3048, 3), (1234, 3), (0, 5)]
        rows, _ = decode([message(s, f) for s, f in cases], POINT)
        for row, (scaled, factor) in zip(rows, cases):
            metres = scaled * 10 ** (-factor)
            self.assertEqual(row["threshold_m"], metres)
            self.assertEqual(row["threshold_ft"], round(metres * 3.28084, 3))

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy not installed")
    def test_wave_threshold_record_identity_parity_and_release(self):
        points = POINT + [{"id": "far", "latitude": 0.0, "longitude": 0.0}]
        messages = [message(1, 0), message(2, 0, parameterNumber=9), message(3, 0, probabilityType=0), message(2, 0)]
        rows, fake = decode(messages, points)
        self.assertEqual([r["threshold_m"] for r in rows], [1, 2])
        self.assertEqual([r["threshold_ft"] for r in rows], [3.281, 6.562])
        self.assertEqual(len({(r["time"], r["cycle"]) for r in rows}), 1)
        self.assertEqual(rows[0]["time"] - rows[0]["cycle"], 3 * 3600)
        near, far = rows[0]["points"]
        self.assertEqual((near["grid"], near["distance_km"], near["percent"]), ([35.0, -121.0], 0.0, 50.0))
        self.assertEqual((far["grid"], far["distance_km"], far["percent"]), (None, None, None))
        self.assertEqual(sorted(fake.released), [0, 1, 2, 3])

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy not installed")
    def test_wave_threshold_refusal_still_releases_handles(self):
        fake = FakeCodes([message(1, 0, parameterNumber=9)])
        with patch.dict(sys.modules, {"eccodes": fake}), self.assertRaises(ValueError):
            wave_ensemble.decode_probabilities(b"GRIB-fake", POINT)
        self.assertEqual(fake.released, [0])

    def test_wave_threshold_guard_regression(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "pipeline" / "wave_ensemble.py"
            f.parent.mkdir()
            f.write_text("x = 1\nft = m * 3.28084\n")
            self.assertEqual(scan(Path(tmp), {}), [
                "pipeline/wave_ensemble.py:2: ft/m/kt/nmi literal outside util/units.py; import it from skippercast.util.units"])


if __name__ == "__main__":
    unittest.main()

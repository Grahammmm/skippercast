"""RF0330-9: GEFS wave probability spatial arrays must be nonempty, one-dimensional and identically shaped."""
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from skippercast.pipeline import wave_ensemble
from tests.unit.test_wave_ensemble_units import POINT, FakeCodes, message

REFUSAL = "GEFS wave probability spatial arrays must be nonempty matching one-dimensional arrays"
NEAR_SECOND = [{"id": "q", "latitude": 35.25, "longitude": -121.25}]
needs_numpy = unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy not installed")


def run(messages, points=POINT):
    fake = FakeCodes(messages)
    with patch.dict(sys.modules, {"eccodes": fake}):
        return wave_ensemble.decode_probabilities(b"GRIB-fake", points), fake


def refused(case, messages, points=POINT):
    fake = FakeCodes(messages)
    with case.subTest(points=points), patch.dict(sys.modules, {"eccodes": fake}), \
            case.assertRaises(ValueError) as caught:
        wave_ensemble.decode_probabilities(b"GRIB-fake", points)
    case.assertEqual(str(caught.exception), REFUSAL)
    return fake


@needs_numpy
class WaveEnsembleShapeTests(unittest.TestCase):
    def test_broadcastable_singletons_are_not_spatial_grids(self):
        cases = {"lat": {"latitudes": [35.0]}, "lon": {"longitudes": [-121.0]}, "values": {"values": [0.5]}}
        for name, over in cases.items():
            for points in (POINT, NEAR_SECOND, []):
                with self.subTest(array=name):
                    refused(self, [message(1, 0, **over)], points)

    def test_spatial_cardinality_and_dimension_matrix(self):
        bad = {
            "unequal": {"latitudes": [35.0, 35.25, 35.5]},
            "empty lat": {"latitudes": []},
            "empty lon": {"longitudes": []},
            "empty values": {"values": []},
            "all empty": {"latitudes": [], "longitudes": [], "values": []},
            "scalar": {"latitudes": 35.0, "longitudes": -121.0, "values": 0.5},
            "scalar values": {"values": 0.5},
            "2d values": {"values": [[0.5, 0.25]]},
            "all 2d": {"latitudes": [[35.0, 35.25]], "longitudes": [[-121.0, -121.25]], "values": [[0.5, 0.25]]},
        }
        for name, over in bad.items():
            with self.subTest(case=name):
                refused(self, [message(1, 0, **over)])
        rows, _ = run([message(1, 0, latitudes=[35.0], longitudes=[-121.0], values=[0.5])])
        self.assertEqual(rows[0]["points"][0]["percent"], 50.0)
        rows, _ = run([message(1, 0)])
        self.assertEqual(rows[0]["points"][0]["percent"], 50.0)

    def test_shape_refusal_releases_and_returns_no_partial_body(self):
        fake = refused(self, [message(1, 0, values=[0.5])])
        self.assertEqual(fake.released, [0])
        fake = refused(self, [message(1, 0), message(2, 0, latitudes=[35.0])])
        self.assertEqual(fake.released, [0, 1])
        ignored = [message(1, 0, parameterNumber=9, values=[0.5]), message(2, 0, probabilityType=0, latitudes=[]),
                   message(3, 0)]
        rows, fake = run(ignored)
        self.assertEqual([r["threshold_m"] for r in rows], [3])
        self.assertEqual(fake.released, [0, 1, 2])

    def test_complete_missing_grid_is_an_honest_gap(self):
        gap = {"point_id": "p", "requested": [35.0, -121.0], "grid": None, "distance_km": None, "percent": None}
        rows, _ = run([message(1, 0, values=[float("nan"), 2.0])])
        self.assertEqual(rows[0]["points"], [gap])
        rows, _ = run([message(1, 0, latitudes=[10.0], longitudes=[10.0], values=[0.5])])
        self.assertEqual(rows[0]["points"], [gap])
        rows, _ = run([message(1, 0, values=[0.0, 1.0]), message(2, 0, values=[1.0, 0.25])],
                      POINT + NEAR_SECOND)
        got = [(p["grid"], p["distance_km"], p["percent"]) for r in rows for p in r["points"]]
        self.assertEqual(got, [([35.0, -121.0], 0.0, 0.0), ([35.25, -121.25], 0.0, 100.0),
                               ([35.0, -121.0], 0.0, 100.0), ([35.25, -121.25], 0.0, 25.0)])
        rows, _ = run([message(1, 0, longitudes=[239.0, 238.75])])
        self.assertEqual(rows[0]["points"][0]["grid"], [35.0, -121.0])


class CodesByBody(FakeCodes):
    """Per-call reader: each decode_probabilities call starts a fresh FakeCodes chosen by the body text."""

    def __init__(self, table):
        super().__init__([])
        self.table, self.current = table, None

    def codes_grib_new_from_file(self, file):
        if file.tell() == 0:
            self.current = FakeCodes(self.table[file.read()])
        return self.current.codes_grib_new_from_file(file)

    def codes_get(self, gid, key):
        return self.current.codes_get(gid, key)

    def codes_get_array(self, gid, key):
        return self.current.codes_get_array(gid, key)

    def codes_release(self, gid):
        self.current.codes_release(gid)


class SequentialPool:
    def __init__(self, max_workers):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, items):
        return [fn(i) for i in items]


class FakeClient:
    names = ("f000", "f003", "f168")

    def __init__(self, bodies):
        self.bodies = bodies

    def get(self, url, as_binary=False):
        if not as_binary:
            return " ".join(f"gefs.wave.t00z.prob.global.0p25.{n}.grib2" for n in self.names)
        for name, body in self.bodies.items():
            if f".{name}." in url or f"{name}.grib2" in url:
                return body
        raise AssertionError(url)


REGION = {"bounds": [-122.0, 34.0, -120.0, 36.0], "forecast_points": POINT}
NOW = datetime(2026, 11, 9, 3, tzinfo=timezone.utc)


@needs_numpy
class WaveProbabilitiesIsolationTests(unittest.TestCase):
    def wave(self, bodies, table):
        with patch.dict(sys.modules, {"eccodes": CodesByBody(table)}), \
                patch.object(wave_ensemble, "ThreadPoolExecutor", SequentialPool):
            return wave_ensemble.wave_probabilities(FakeClient(bodies), REGION, NOW)

    def test_malformed_file_isolated_from_valid_sibling(self):
        bodies = {"f000": b"GRIB-good", "f003": b"GRIB-bad", "f168": b"GRIB-good"}
        table = {b"GRIB-good": [message(1, 0)], b"GRIB-bad": [message(1, 0, latitudes=[35.0])]}
        result = self.wave(bodies, table)
        self.assertEqual(len(result["frames"]), 2)
        self.assertEqual([f["points"][0]["percent"] for f in result["frames"]], [50.0, 50.0])
        self.assertEqual(len(result["failed_files"]), 1)
        self.assertIn("f003", result["failed_files"][0]["file"])
        self.assertEqual(result["failed_files"][0]["error"], REFUSAL)

    def test_all_files_malformed_keeps_wrapper_error(self):
        bodies = {n: b"GRIB-bad" for n in FakeClient.names}
        table = {b"GRIB-bad": [message(1, 0, values=[0.5])]}
        with self.assertRaises(ValueError) as caught:
            self.wave(bodies, table)
        self.assertTrue(str(caught.exception).startswith("No valid regional GEFS wave probabilities: "))
        self.assertIn(REFUSAL, str(caught.exception))


if __name__ == "__main__":
    unittest.main()

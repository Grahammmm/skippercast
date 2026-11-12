"""RF1530-13: impossible source latitudes never qualify as GEFS-wave nearest populated cells."""
import importlib.util
import sys
import unittest
from unittest.mock import patch

from skippercast.pipeline import wave_ensemble
from tests.unit.test_wave_ensemble_units import POINT, FakeCodes, message

GAP = {"point_id": "p", "requested": [35.0, -121.0], "grid": None, "distance_km": None, "percent": None}
NAN, INF = float("nan"), float("inf")


def run(messages, points=POINT):
    fake = FakeCodes(messages)
    with patch.dict(sys.modules, {"eccodes": fake}):
        return wave_ensemble.decode_probabilities(b"GRIB-fake", points), fake


def one(lat, lon=-121.0, value=0.9, **over):
    over.setdefault("latitudes", [lat])
    over.setdefault("longitudes", [lon])
    over.setdefault("values", [value])
    rows, fake = run([message(1, 0, **over)])
    return rows[0]["points"][0], fake


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy not installed")
class WaveEnsembleLatitudeTests(unittest.TestCase):
    def test_wrapped_latitudes_cannot_supply_probabilities(self):
        for lat in (395.0, -325.0, 90.01, -90.01, 270.0, 450.0):
            with self.subTest(latitude=lat):
                sample, _ = one(lat)
                self.assertEqual(sample, GAP)

    def test_invalid_nearest_yields_to_valid_sibling(self):
        # The invalid cell is nearer (zero distance) and has the higher probability.
        lats, lons, vals = [395.0, 35.1], [239.0, 239.0], [0.9, 0.2]
        for order in (slice(None), slice(None, None, -1)):
            with self.subTest(reversed=order.step == -1):
                sample, _ = one(None, latitudes=lats[order], longitudes=lons[order], values=vals[order])
                self.assertEqual(sample["grid"], [35.1, -121.0])
                self.assertEqual(sample["percent"], 20.0)
                self.assertTrue(0 < sample["distance_km"] < 30)
                self.assertEqual((sample["point_id"], sample["requested"]), ("p", [35.0, -121.0]))

    def test_invalid_only_and_valid_far_are_explicit_gaps(self):
        cases = {
            "invalid only": ([395.0, -325.0], [239.0, 239.0], [0.9, 0.8]),
            "invalid plus far valid": ([395.0, 10.0], [239.0, 239.0], [0.9, 0.5]),
            "nan": ([NAN], [239.0], [0.9]),
            "positive infinity": ([INF], [239.0], [0.9]),
            "negative infinity": ([-INF], [239.0], [0.9]),
        }
        for name, (lats, lons, vals) in cases.items():
            with self.subTest(case=name):
                rows, _ = run([message(1, 0, latitudes=lats, longitudes=lons, values=vals),
                               message(2, 0, latitudes=lats, longitudes=lons, values=vals)])
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(r["points"] == [GAP] for r in rows))

    def test_physical_latitude_endpoints_remain_eligible(self):
        for lat in (-90.0, 90.0, 0.0, 35.0):
            with self.subTest(latitude=lat):
                point = [{"id": "p", "latitude": lat, "longitude": -121.0}]
                rows, _ = run([message(1, 0, latitudes=[lat], longitudes=[-121.0], values=[0.5])], point)
                sample = rows[0]["points"][0]
                self.assertEqual((sample["grid"], sample["distance_km"], sample["percent"]),
                                 ([lat, -121.0], 0.0, 50.0))

    def test_valid_probability_and_longitude_contract_unchanged(self):
        sample, _ = one(None, latitudes=[35.0, 35.0, 35.0], longitudes=[239.0, 239.0, 239.0], values=[0.0, 0.5, 1.0])
        self.assertEqual((sample["grid"], sample["distance_km"], sample["percent"]), ([35.0, -121.0], 0.0, 0.0))
        for value, percent in ((0.0, 0.0), (0.5, 50.0), (1.0, 100.0)):
            sample, _ = one(35.0, 239.0, value)
            self.assertEqual((sample["grid"], sample["percent"]), ([35.0, -121.0], percent))
        far, _ = one(10.0, 239.0, 0.5)
        self.assertEqual(far, GAP)
        # An invalid probability stays unavailable independently of the latitude.
        sample, _ = one(None, latitudes=[35.0, 35.1], longitudes=[-121.0, -121.0], values=[NAN, 0.2])
        self.assertEqual((sample["grid"], sample["percent"]), ([35.1, -121.0], 20.0))
        sample, _ = one(35.0, value=NAN)
        self.assertEqual(sample, GAP)

    def test_handles_release_for_gaps_and_ignored_messages(self):
        messages = [message(1, 0), message(2, 0, parameterNumber=9),
                    message(3, 0, latitudes=[395.0, 35.1], longitudes=[239.0, 239.0], values=[0.9, 0.2]),
                    message(4, 0, probabilityType=0), message(5, 0, latitudes=[395.0, -325.0], values=[0.9, 0.9])]
        rows, fake = run(messages)
        self.assertEqual([r["threshold_m"] for r in rows], [1, 3, 5])
        self.assertEqual(rows[1]["points"][0]["grid"], [35.1, -121.0])
        self.assertEqual(rows[2]["points"], [GAP])
        self.assertEqual(sorted(fake.released), [0, 1, 2, 3, 4])
        self.assertEqual(len(fake.released), 5)


if __name__ == "__main__":
    unittest.main()

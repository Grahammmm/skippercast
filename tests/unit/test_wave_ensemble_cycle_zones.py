"""Equivalent aware clocks must select the same GEFS-wave cycle (offline, synthetic)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from skippercast.pipeline import wave_ensemble

REGION = {"bounds": [-122.0, 34.0, -120.0, 36.0], "forecast_points": []}
UTC_NOW = datetime(2026, 9, 27, 9, 30, tzinfo=timezone.utc)
ZONES = (timezone.utc, timezone(timedelta(hours=5, minutes=30)), timezone(timedelta(hours=-7)))


def cycle_ts(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


class Client:
    def __init__(self, complete):
        self.complete = complete  # set of "YYYYMMDD/HH" listings with the full lead grid
        self.urls = []

    def get(self, url, as_binary=False):
        self.urls.append(url)
        if as_binary:
            name = parse_qs(urlparse(url).query)["file"][0]
            return int(name.split(".")[-2][1:])
        key = url.split("gefs.")[1][:11]
        if key in self.complete:
            return " ".join(f"gefs.wave.t{key[-2:]}z.prob.global.0p25.f{lead:03}.grib2" for lead in range(0, 169, 3))
        return ""


def run(now, complete, decoded_cycle):
    client = Client(complete)
    def decode(lead, points):
        return [{"cycle": decoded_cycle, "time": decoded_cycle + lead * 3600, "threshold_m": 1, "points": []}]
    with patch.object(wave_ensemble, "decode_probabilities", decode):
        out = wave_ensemble.wave_probabilities(client, REGION, now)
    # Listing order is significant; worker thread scheduling for file requests is not.
    return [u for u in client.urls if "?" not in u] + sorted(u for u in client.urls if "?" in u), out


class WaveCycleZoneTests(unittest.TestCase):
    def test_equivalent_aware_clocks_select_identical_wave_cycle(self):
        want = cycle_ts(2026, 9, 27, 6)
        results = [run(UTC_NOW.astimezone(z), {"20260927/06"}, want) for z in ZONES]
        self.assertEqual(results[0][1]["issued_at"], "2026-09-27T06:00:00Z")
        for urls, out in results[1:]:
            self.assertEqual(urls, results[0][0])
            self.assertEqual(out, results[0][1])
        self.assertIn("gefs.20260927/06/wave/gridded/", results[0][0][0])

    def test_zoned_clock_crossing_utc_date_boundary(self):
        now = datetime(2026, 9, 27, 0, 30, tzinfo=timezone(timedelta(hours=-7))) # 07:30 UTC same day
        other = datetime(2026, 9, 26, 22, 0, tzinfo=timezone(timedelta(hours=-9))) # 07:00 UTC
        late = datetime(2026, 9, 28, 4, 10, tzinfo=timezone(timedelta(hours=5, minutes=30))) # 22:40 UTC on 27th
        for clock, key, ts in ((now, "20260927/06", cycle_ts(2026, 9, 27, 6)),
                               (other, "20260927/06", cycle_ts(2026, 9, 27, 6)),
                               (late, "20260927/18", cycle_ts(2026, 9, 27, 18))):
            urls, out = run(clock, {key}, ts)
            self.assertTrue(urls[0].endswith(f"gefs.{key[:8]}/{key[9:]}/wave/gridded/"), urls[0])
            self.assertEqual(out["issued_at"], datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_incomplete_latest_listing_falls_back_identically(self):
        want = cycle_ts(2026, 9, 27, 0)
        results = [run(UTC_NOW.astimezone(z), {"20260927/00"}, want) for z in ZONES]
        self.assertEqual([u for u, _ in results[0:1]][0][:2],
                         [f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/gefs.20260927/{h}/wave/gridded/" for h in ("06", "00")])
        for urls, out in results[1:]:
            self.assertEqual(urls, results[0][0])
            self.assertEqual(out["issued_at"], "2026-09-27T00:00:00Z")
        for z in ZONES:
            with self.assertRaisesRegex(ValueError, "No recent GEFS Wave probability files"):
                run(UTC_NOW.astimezone(z), set(), want)

    def test_cycle_mismatch_still_refuses_genuine_wrong_run(self):
        for z in ZONES:
            with self.assertRaisesRegex(ValueError, "Wave ensemble cycle mismatch"):
                run(UTC_NOW.astimezone(z), {"20260927/06"}, cycle_ts(2026, 9, 27, 0))


if __name__ == "__main__":
    unittest.main()

"""GEFS wind-ensemble builder: URLs, cycle choice, range coalescing, sea-cell sampling and keep-previous."""
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.forecast import ensemble

CYCLE = datetime(2026, 9, 27, 0, tzinfo=timezone.utc)
HAS_ECCODES = importlib.util.find_spec('eccodes') is not None and importlib.util.find_spec('numpy') is not None


class LocationTests(unittest.TestCase):
    def test_member_urls_follow_the_noaa_bucket_layout(self):
        self.assertEqual(ensemble.gefs_url(CYCLE, 0, 0),
                         'https://noaa-gefs-pds.s3.amazonaws.com/gefs.20260927/00/atmos/pgrb2sp25/gec00.t00z.pgrb2s.0p25.f000')
        self.assertTrue(ensemble.gefs_url(CYCLE, 30, 192).endswith('/gep30.t00z.pgrb2s.0p25.f192'))
        self.assertEqual(ensemble.mask_url(CYCLE),
                         'https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20260927/00/atmos/gfs.t00z.pgrb2.0p25.f000')
        with self.assertRaises(ValueError):
            ensemble.member_name(31)
        self.assertNotIn('open-meteo', ensemble.gefs_url(CYCLE, 1, 3) + ensemble.DOCUMENTATION)

    def test_latest_cycle_needs_control_and_last_member_final_step(self):
        now = datetime(2026, 9, 27, 9, 30, tzinfo=timezone.utc)
        seen = []
        published = {ensemble.gefs_url(CYCLE, 0, 192) + '.idx', ensemble.gefs_url(CYCLE, 30, 192) + '.idx'}

        def exists(url):
            seen.append(url)
            return url in published
        self.assertEqual(ensemble.latest_cycle(now, exists=exists), CYCLE)
        # 06z was checked first (too early for 12z) and was incomplete.
        self.assertIn('gefs.20260927/06/', seen[0])
        published.discard(ensemble.gefs_url(CYCLE, 30, 192) + '.idx')
        self.assertNotEqual(ensemble.latest_cycle(now, lookback_hours=9, exists=exists), CYCLE)

    def test_every_intelligence_region_contributes_its_forecast_points(self):
        regions = ensemble.region_points()
        self.assertIn('morro-bay', regions)
        self.assertTrue(all(points for points in regions.values()))

    def test_grib_splitting_rejects_error_pages_and_truncation(self):
        with self.assertRaises(ValueError):
            ensemble.split_messages(b'<html>SlowDown</html>')
        message = b'GRIB\x00\x00\x00\x02' + (20).to_bytes(8, 'big') + b'7777'
        self.assertEqual(ensemble.split_messages(message * 2), [message, message])
        with self.assertRaises(ValueError):
            ensemble.split_messages(message[:-1])


def grib(values, lat1=36.0, lat2=35.0, lon1=238.0, lon2=240.0):
    import eccodes
    import numpy as np
    handle = eccodes.codes_grib_new_from_samples('regular_ll_sfc_grib2')
    try:
        for key, value in (('Ni', 9), ('Nj', 5), ('latitudeOfFirstGridPointInDegrees', lat1),
                           ('latitudeOfLastGridPointInDegrees', lat2), ('longitudeOfFirstGridPointInDegrees', lon1),
                           ('longitudeOfLastGridPointInDegrees', lon2), ('iDirectionIncrementInDegrees', 0.25),
                           ('jDirectionIncrementInDegrees', 0.25)):
            eccodes.codes_set(handle, key, value)
        eccodes.codes_set_values(handle, np.asarray(values, dtype=float).ravel())
        return eccodes.codes_get_message(handle)
    finally:
        eccodes.codes_release(handle)


class FakeBucket:
    """Serves synthetic GRIB files and NOAA-style .idx files, honouring byte ranges."""

    def __init__(self, members, steps, absent=()):
        import numpy as np
        self.files, self.calls = {}, []
        land = np.zeros((5, 9))
        land[:, 8] = 1  # the easternmost column (-120.0) is land
        self.add(ensemble.mask_url(CYCLE), [('LAND', 'surface', 'anl', grib(land))])
        for member in range(members):
            for step in steps:
                if (member, step) in absent:
                    continue
                self.add(ensemble.gefs_url(CYCLE, member, step), [
                    ('GUST', 'surface', f'{step} hour fcst', grib(np.full((5, 9), 10.0 + step))),
                    ('TMP', '2 m above ground', f'{step} hour fcst', grib(np.full((5, 9), 290.0))),
                    ('UGRD', '10 m above ground', f'{step} hour fcst', grib(np.full((5, 9), 3.0 + member))),
                    ('VGRD', '10 m above ground', f'{step} hour fcst', grib(np.full((5, 9), 4.0))),
                    ('PRMSL', 'mean sea level', f'{step} hour fcst', grib(np.full((5, 9), 101325.0))),
                ])

    def add(self, url, messages):
        body, lines, offset = b'', [], 0
        for number, (var, level, forecast, blob) in enumerate(messages, 1):
            lines.append(f'{number}:{offset}:d={CYCLE:%Y%m%d%H}:{var}:{level}:{forecast}:ENS=+1')
            body += blob
            offset += len(blob)
        self.files[url] = body
        self.files[url + '.idx'] = ('\n'.join(lines) + '\n').encode()

    def __call__(self, url, byte_range=None, **_):
        self.calls.append((url, byte_range))
        body = self.files.get(url)
        if body is None or byte_range is None:
            return body
        start, end = byte_range
        return body[start:None if end is None else end + 1]


@unittest.skipUnless(HAS_ECCODES, 'Optional GRIB decoder not installed')
class BuildTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(ensemble, MEMBERS=3, STEPS=(0, 3, 6, 9))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.exists = lambda url: True
        self.regions = {'test-region': [(35.5, -121.5), (35.5, -120.0), (35.5, -118.0)]}

    def build(self, output, bucket, previous=None, force=False):
        return ensemble.build(output, previous, force, now=datetime(2026, 9, 27, 5, tzinfo=timezone.utc),
                              regions=self.regions, http=bucket, exists=self.exists, log=lambda *_: None)

    def test_members_are_sampled_at_the_nearest_sea_cell_with_receipts(self):
        bucket = FakeBucket(3, (0, 3, 6, 9), absent={(2, 6)})
        with tempfile.TemporaryDirectory() as tmp:
            status = self.build(Path(tmp), bucket)
            self.assertEqual((status['status'], status['state'], status['missing_member_steps']), ('ok', 'built', 1))
            manifest = json.loads(Path(tmp, 'ncep_gefs025/manifest.json').read_text())
            region = json.loads(Path(tmp, 'ncep_gefs025/regions/test-region.json').read_text())
        self.assertEqual(manifest['meta']['last_run_initialisation_time'], int(CYCLE.timestamp()))
        self.assertEqual(manifest['upstream']['cycle_prefix'], ensemble.cycle_prefix(CYCLE))
        self.assertEqual(manifest['upstream']['missing'], [{'member': 2, 'step': 6, 'fields': ['u10', 'v10', 'gust']}])
        self.assertEqual(manifest['upstream']['messages'], (3 * 4 - 1) * 3)
        self.assertRegex(manifest['upstream']['messages_sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(region['times'], [int(CYCLE.timestamp()) + h * 3600 for h in (0, 3, 6, 9)])
        exact, coastal, inland = region['points']
        self.assertEqual((exact['grid'], exact['distance_km']), ([35.5, -121.5], 0.0))
        self.assertEqual(coastal['grid'], [35.5, -120.25])  # land cell skipped
        self.assertAlmostEqual(coastal['distance_km'], 22.67, places=1)
        self.assertEqual((inland['grid'], inland['wind_speed_10m'][0][0]), (None, None))
        self.assertAlmostEqual(exact['wind_speed_10m'][1][0], math.hypot(4, 4), places=2)
        self.assertAlmostEqual(exact['wind_gusts_10m'][0][2], 16, places=2)
        self.assertIsNone(exact['wind_speed_10m'][2][2])
        # UGRD and VGRD are adjacent: one range request per member-step for both.
        member_ranges = [c for c in bucket.calls if c[1] and 'pgrb2sp25' in c[0]]
        self.assertEqual(len(member_ranges), (3 * 4 - 1) * 2)

    def test_too_many_missing_member_steps_fail_and_keep_the_previous_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous, output = Path(tmp, 'published'), Path(tmp, 'out')
            self.assertEqual(self.build(previous, FakeBucket(3, (0, 3, 6, 9)))['state'], 'built')
            status = self.build(output, FakeBucket(3, (0, 3, 6, 9), absent={(0, 0), (1, 3)}), previous, force=True)
            self.assertEqual((status['status'], status['kept_previous']), ('failed', True))
            self.assertIn('member-steps incomplete', status['issue'])
            self.assertEqual(Path(output, 'ncep_gefs025/manifest.json').read_text(),
                             Path(previous, 'ncep_gefs025/manifest.json').read_text())
            reused = self.build(output, FakeBucket(3, (0, 3, 6, 9)), previous)
            self.assertEqual(reused['state'], 'current')

    def test_grid_change_between_mask_and_members_is_rejected(self):
        import numpy as np
        bucket = FakeBucket(3, (0, 3, 6, 9))
        bucket.add(ensemble.mask_url(CYCLE), [('LAND', 'surface', 'anl', grib_shape(np.zeros((4, 9))))])
        with tempfile.TemporaryDirectory() as tmp:
            failed = self.build(Path(tmp), bucket)
        self.assertEqual((failed['status'], failed['kept_previous']), ('failed', False))
        self.assertIn('differs from the land mask', failed['issue'])


def grib_shape(values):
    import eccodes
    import numpy as np
    handle = eccodes.codes_grib_new_from_samples('regular_ll_sfc_grib2')
    try:
        nj, ni = values.shape
        for key, value in (('Ni', ni), ('Nj', nj), ('latitudeOfFirstGridPointInDegrees', 36.0),
                           ('latitudeOfLastGridPointInDegrees', 36.0 - 0.25 * (nj - 1)),
                           ('longitudeOfFirstGridPointInDegrees', 238.0), ('longitudeOfLastGridPointInDegrees', 240.0),
                           ('iDirectionIncrementInDegrees', 0.25), ('jDirectionIncrementInDegrees', 0.25)):
            eccodes.codes_set(handle, key, value)
        eccodes.codes_set_values(handle, np.asarray(values, dtype=float).ravel())
        return eccodes.codes_get_message(handle)
    finally:
        eccodes.codes_release(handle)


if __name__ == '__main__':
    unittest.main()

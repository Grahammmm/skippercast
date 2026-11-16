"""GEFS land mask: invalid land fractions (negative, nonfinite, >1) never qualify a cell as sea."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from skippercast.forecast import ensemble
from tests.unit.test_forecast_ensemble import CYCLE, HAS_ECCODES, FakeBucket, grib

NOW = datetime(2026, 9, 27, 5, tzinfo=timezone.utc)
LATS = [36.0, 35.75, 35.5, 35.25, 35.0]
LONS = [-122.0 + 0.25 * i for i in range(9)]


def no_network(*args, **kwargs):
    raise AssertionError('unexpected network')


def land_with(**cells):
    """5x9 land (1.0) grid with {'r2c2': value} overrides."""
    import numpy as np
    land = np.ones((5, 9))
    for key, value in cells.items():
        r, c = key[1:].split('c')
        land[int(r), int(c)] = value
    return land


def mask_bucket(land, extra=None):
    bucket = FakeBucket(1, (0,))
    bucket.add(ensemble.mask_url(CYCLE), [('LAND', 'surface', 'anl', grib(land))])
    return bucket


@unittest.skipUnless(HAS_ECCODES, 'Optional GRIB decoder not installed')
class MaskValueTests(unittest.TestCase):
    def test_read_mask_rejects_negative_and_nonfinite_fractions(self):
        import numpy as np
        grid = np.zeros((5, 9))
        bad = [-999.0, -1e-9, -np.inf, np.inf, np.nan, 1.5, 1000.0]
        for i, value in enumerate(bad):
            grid[0, i] = value
        before = grid.copy()
        bucket = mask_bucket(np.zeros((5, 9)))
        lats, lons = np.array(LATS), np.array(LONS) % 360
        with patch.object(ensemble, 'decode_one', return_value=(grid, lats, lons)):
            _, _, sea, _, _ = ensemble.read_mask(CYCLE, http=bucket)
        expected = np.ones((5, 9), dtype=bool)
        expected[0, :len(bad)] = False
        self.assertTrue(np.array_equal(sea, expected))
        self.assertTrue(np.array_equal(grid, before, equal_nan=True))

    def test_read_mask_preserves_fraction_threshold_and_receipts(self):
        import numpy as np
        below = float(np.nextafter(0.5, 0.0))
        values = [0.0, 0.25, 0.5, 0.75, 1.0]
        land = np.ones((5, 9))
        land[2, :len(values)] = values
        bucket = mask_bucket(land)
        lats, lons, sea, url, sha = ensemble.read_mask(CYCLE, http=bucket)
        self.assertEqual(list(sea[2, :len(values)]), [True, True, False, False, False])
        # GRIB packs float32, so the representable value just below 0.5 goes through the decode seam.
        seam = np.array([[0.0, 0.25, below, 0.5, 0.75, 1.0]])
        with patch.object(ensemble, 'decode_one', return_value=(seam, np.array([35.5]), np.arange(6.0))):
            self.assertEqual(list(ensemble.read_mask(CYCLE, http=bucket)[2][0]), [True, True, True, False, False, False])
        self.assertFalse(sea[0].any())
        self.assertEqual(list(lats), sorted(LATS))  # the decoder returns ascending axes
        self.assertEqual(len(lons), 9)
        self.assertAlmostEqual(float(lons[0]) % 360, 238.0)
        self.assertEqual(url, ensemble.mask_url(CYCLE))
        self.assertEqual(len(bucket.calls), 4)  # idx + range per read_mask call; seam call reuses transport
        self.assertEqual(sha, hashlib.sha256(bucket.files[url]).hexdigest())  # mask is the only message
        self.assertEqual([c[0] for c in bucket.calls][:2], [url + '.idx', url])
        self.assertIsNotNone(bucket.calls[1][1])

    def build_point(self, mask_value):
        bucket = mask_bucket(land_with(r2c2=mask_value))
        with patch.object(socket.socket, 'connect', no_network), \
                patch.multiple(ensemble, MEMBERS=1, STEPS=(0,)), tempfile.TemporaryDirectory() as tmp:
            result = ensemble.build(Path(tmp), force=True, now=NOW, regions={'synthetic': [(35.5, -121.5)]},
                                    http=bucket, exists=lambda _: True, log=lambda *_: None)
            point = json.loads(Path(tmp, ensemble.MODEL_ID, 'regions/synthetic.json').read_text())['points'][0]
        self.assertTrue(any(u == ensemble.mask_url(CYCLE) and r is not None for u, r in bucket.calls))
        self.assertEqual((result['status'], result['state']), ('ok', 'built'))
        self.assertEqual((point['latitude'], point['longitude']), (35.5, -121.5))
        return point

    def test_negative_mask_grib_does_not_create_sea_sample(self):
        sea = self.build_point(0.0)
        self.assertEqual((sea['grid'], sea['wind_speed_10m'], sea['wind_gusts_10m']), ([35.5, -121.5], [[5.0]], [[10.0]]))
        land = self.build_point(1.0)
        self.assertEqual((land['grid'], land['distance_km'], land['wind_speed_10m'], land['wind_gusts_10m']),
                         (None, None, [[None]], [[None]]))
        bad = self.build_point(-999.0)
        self.assertEqual((bad['grid'], bad['distance_km'], bad['wind_speed_10m'], bad['wind_gusts_10m']),
                         (None, None, [[None]], [[None]]))

    def test_invalid_nearest_mask_cell_cannot_shadow_valid_sea(self):
        import numpy as np
        # exact cell r2c2 invalid; r2c3 (~22.7 km east) valid sea; r2c6 valid but ~68 km away (outside radius)
        land = land_with(r2c2=-999.0, r2c3=0.0, r2c6=0.0)
        bucket = mask_bucket(land)
        u = np.full((5, 9), 3.0)
        u[2, 2], u[2, 3], u[2, 6] = 30.0, 6.0, 60.0
        gust = np.full((5, 9), 10.0)
        gust[2, 2], gust[2, 3], gust[2, 6] = 99.0, 12.0, 98.0
        bucket.add(ensemble.gefs_url(CYCLE, 0, 0), [
            ('GUST', 'surface', '0 hour fcst', grib(gust)),
            ('UGRD', '10 m above ground', '0 hour fcst', grib(u)),
            ('VGRD', '10 m above ground', '0 hour fcst', grib(np.zeros((5, 9)))),
        ])
        lats, lons, sea, _, _ = ensemble.read_mask(CYCLE, http=bucket)
        cell = ensemble.nearest_sea(lats, lons, sea, 35.5, -121.5)
        self.assertEqual(cell[:2], (2, 3))
        with patch.multiple(ensemble, MEMBERS=1, STEPS=(0,)):
            samples, _ = ensemble.collect(CYCLE, [(35.5, -121.5)], http=bucket, workers=1, log=lambda *_: None)
        s = samples[0]
        self.assertEqual((s['grid'], s['wind_speed_10m'], s['wind_gusts_10m']), ([35.5, -121.25], [[6.0]], [[12.0]]))
        self.assertAlmostEqual(s['distance_km'], 22.67, places=1)
        # only the far valid cell remains: outside radius, so no fallback
        far = mask_bucket(land_with(r2c2=-999.0, r2c6=0.0))
        lats, lons, sea, _, _ = ensemble.read_mask(CYCLE, http=far)
        self.assertIsNone(ensemble.nearest_sea(lats, lons, sea, 35.5, -121.5))

    def test_all_invalid_mask_matches_no_sea_behavior(self):
        import numpy as np
        grid = np.full((5, 9), -999.0)
        grid[0], grid[1], grid[2] = np.nan, np.inf, -np.inf
        lats, lons = np.array(LATS), np.array(LONS) % 360
        with patch.object(ensemble, 'decode_one', return_value=(grid, lats, lons)):
            _, _, sea, _, _ = ensemble.read_mask(CYCLE, http=mask_bucket(np.zeros((5, 9))))
        self.assertFalse(sea.any())
        self.assertIsNone(ensemble.nearest_sea(lats, lons, sea, 35.5, -121.5))


if __name__ == '__main__':
    unittest.main()

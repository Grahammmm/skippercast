"""Forecast tiles: wave directions are regridded as circular bearings, so 359/1 degrees stays north."""
import base64
from datetime import datetime, timezone
import unittest
from unittest import mock

import numpy as np

from skippercast.forecast import build
from skippercast.forecast.models import Field, Model

CYCLE = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
FINE_LATS, FINE_LONS = np.array([34.0, 34.5, 35.0]), np.array([-121.0, -120.5, -120.0])
COARSE_LATS, COARSE_LONS = np.array([34.0, 35.0]), np.array([-121.0, -120.0])
DIRECTIONS = ('wave_direction', 'wind_wave_direction', 'swell_wave_direction', 'secondary_swell_wave_direction')


def model_with(name):
    fields = (Field('wave_height', ('HTSGW', 'surface'), 0.01), Field(name, ('WVDIR', 'surface'), 0.1))
    return Model(id='fake_model', name='Fake', provider='Test', kind='wave', family='gfs', cycles=(0, 12),
                 steps=(0,), fields=fields, resolution_km=1, documentation='https://example.invalid')


def fetch(name, direction_grid, direction_axes=(COARSE_LATS, COARSE_LONS), height=None):
    """Real fetch_model on a synthetic one-step model; only plan/download/decode/subset are injected."""
    height = np.ones((3, 3)) if height is None else height
    sources = {'wave_height': (height, FINE_LATS, FINE_LONS), name: (direction_grid, *direction_axes)}
    sources = {key: (np.array(value[0], dtype=float), value[1], value[2]) for key, value in sources.items()}
    snapshot = {key: value[0].copy() for key, value in sources.items()}
    with mock.patch.object(build, 'plan_step', lambda m, c, s, wanted: [(n, n, None) for n, _ in wanted]), \
            mock.patch.object(build, 'download_all', lambda plan, workers: {n: url for n, url, _ in plan}), \
            mock.patch.object(build, 'decode', lambda blob: sources[blob]), \
            mock.patch.object(build, 'subset', lambda grid, lats, lons: (grid, lats, lons)):
        result = build.fetch_model(model_with(name), CYCLE, workers=4, log=lambda _: None)
    for key, before in snapshot.items():  # decoded source arrays are never mutated
        np.testing.assert_array_equal(sources[key][0], before)
    return result


def stored(cube, scale):
    return np.frombuffer(base64.b64decode(build.quantize(cube, scale)), dtype='<i2').reshape(cube.shape)


def circular_mean(angles):
    radians = np.radians(angles)
    return float(np.degrees(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360)


def angular_gap(a, b):
    return abs((a - b + 180) % 360 - 180)


class FetchModelDirectionTests(unittest.TestCase):
    def test_fetch_model_wave_direction_crosses_north_not_south(self):
        for name in DIRECTIONS:
            with self.subTest(field=name):
                times, lats, lons, cubes, sea = fetch(name, [[359.0, 1.0], [359.0, 1.0]])
                self.assertEqual(times, [int(CYCLE.timestamp())])
                self.assertEqual((lats.tolist(), lons.tolist()), (FINE_LATS.tolist(), FINE_LONS.tolist()))
                self.assertEqual(cubes['wave_height'].tolist(), np.ones((1, 3, 3)).tolist())
                self.assertTrue(sea.all())
                direction = cubes[name][0]
                self.assertLess(angular_gap(float(direction[1, 1]), 0.0), 1e-6)
                self.assertEqual(int(stored(cubes[name], 0.1)[0, 1, 1]), 0)  # not 1800

    def test_aligned_direction_grid_is_unchanged(self):
        grid = np.array([[359.0, 1.0, 90.0], [10.0, 20.0, 30.0], [0.0, 180.0, 270.0]])
        with mock.patch.object(build, 'regrid_direction', side_effect=AssertionError('resampled')):
            _, _, _, cubes, _ = fetch('wave_direction', grid, (FINE_LATS, FINE_LONS))
        self.assertEqual(cubes['wave_direction'][0].tolist(), grid.tolist())


class RegridDirectionTests(unittest.TestCase):
    def regrid(self, grid, axes=(COARSE_LATS, COARSE_LONS)):
        return build.regrid_direction(np.array(grid, dtype=float), *axes, FINE_LATS, FINE_LONS)

    def test_direction_regrid_two_axes_and_nonwrap_control(self):
        grid = [[350.0, 10.0], [20.0, 40.0]]
        out = self.regrid(grid)
        radians = np.radians(np.array(grid))
        sin = build.regrid(np.sin(radians), COARSE_LATS, COARSE_LONS, FINE_LATS, FINE_LONS)
        cos = build.regrid(np.cos(radians), COARSE_LATS, COARSE_LONS, FINE_LATS, FINE_LONS)
        gaps = np.abs((out - np.degrees(np.arctan2(sin, cos)) + 180) % 360 - 180)  # independent of the 0/360 seam
        self.assertLess(float(gaps.max()), 1e-6)
        self.assertAlmostEqual(out[1, 1], circular_mean([350.0, 10.0, 20.0, 40.0]), places=6)  # both axes at once
        self.assertAlmostEqual(angular_gap(out[0, 1], circular_mean([350.0, 10.0])), 0.0, places=6)  # north
        # non-wrapping control: midpoint of 10 and 30 stays 20; uniform stays uniform; 0 and 360 are one bearing
        self.assertAlmostEqual(self.regrid([[10.0, 30.0], [10.0, 30.0]])[1, 1], 20.0, places=6)
        np.testing.assert_allclose(self.regrid(np.full((2, 2), 123.0)), 123.0, atol=1e-6)
        np.testing.assert_allclose(self.regrid([[0.0, 360.0], [360.0, 0.0]]), 0.0, atol=1e-6)
        # scalar regrid and the nearest mask path keep their exact values
        scalar = np.array([[1.0, 3.0], [5.0, 7.0]])
        self.assertEqual(build.regrid(scalar, COARSE_LATS, COARSE_LONS, FINE_LATS, FINE_LONS)[1, 1], 4.0)
        self.assertEqual(build.regrid(scalar, COARSE_LATS, COARSE_LONS, FINE_LATS, FINE_LONS, nearest=True).tolist(),
                         [[1.0, 3.0, 3.0], [5.0, 7.0, 7.0], [5.0, 7.0, 7.0]])  # midpoint ties go to the upper cell, as before

    def test_direction_regrid_opposites_and_missing_stay_missing(self):
        for pair in ((90.0, 270.0), (0.0, 180.0)):
            with self.subTest(opposites=pair):
                out = self.regrid([list(pair), list(pair)])
                self.assertTrue(np.isnan(out[:, 1]).all())  # equal and opposite: no invented bearing
        for bad in (np.nan, np.inf, -np.inf, -5.0, 9999.0, 360.5):
            with self.subTest(bad=bad):
                out = self.regrid([[10.0, bad], [10.0, bad]])
                self.assertTrue(np.isnan(out[:, 1:]).all())  # the bad contributor is never normalised in
                self.assertAlmostEqual(out[0, 0], 10.0, places=6)  # the valid edge column is untouched
        # a fully valid neighbourhood next to a missing one stays usable, after quantising too
        _, _, _, cubes, _ = fetch('wave_direction', [[359.0, 1.0], [np.nan, 9999.0]])
        direction = cubes['wave_direction']
        self.assertTrue(np.isnan(direction[0, 2]).all())
        self.assertLess(angular_gap(float(direction[0, 0, 1]), 0.0), 1e-6)
        codes = stored(direction, 0.1)[0]
        self.assertEqual(int(codes[0, 1]), 0)
        self.assertTrue((codes[1:] == build.MISSING).all())


if __name__ == '__main__':
    unittest.main()

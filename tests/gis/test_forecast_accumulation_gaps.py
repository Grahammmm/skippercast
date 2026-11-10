"""Forecast tiles: missing or nonfinite accumulated precipitation stays missing; it never becomes a dry zero."""
import base64
from datetime import datetime, timezone
from dataclasses import replace
import unittest
from unittest import mock
import warnings

import numpy as np

from skippercast.forecast import build
from skippercast.forecast.build import MISSING, convert, quantize
from skippercast.forecast.models import MODELS

CYCLE = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
LATS, LONS = np.array([34.0, 35.0]), np.array([-121.0, -120.0])
ECMWF = MODELS['ecmwf_ifs025']
PRECIP = ECMWF.field('precipitation')
STEPS = (0, 3, 6)
TIMES = [3600 * s for s in STEPS]
NAN, INF = np.nan, np.inf
VALID = [0.0, 0.003, 0.006]          # metres: 1 mm/h over each 3 h interval
VALID_RATE = [0.0, 1.0, 1.0]


def model():
    """The real ECMWF reference and precipitation field definitions on three steps."""
    return replace(ECMWF, steps=STEPS, fields=(ECMWF.field('u10'), PRECIP), mask=())


def accumulated(values):
    return np.array(values, dtype=float).reshape(len(values), 1, 1)


def rates(values):
    """convert() of one cell's accumulations, with every invalid-arithmetic warning turned into an error."""
    with warnings.catch_warnings(), np.errstate(all='raise'):
        warnings.simplefilter('error')
        return convert(ECMWF, 'precipitation', accumulated(values), TIMES)[:, 0, 0]


def fetch(per_step, offered=(0, 3, 6)):
    """fetch_model with only plan/download/decode injected; per_step: {step: 2x2 accumulation grid}."""
    logs = []

    def plan_step(m, cycle, step, wanted):
        return [(name, (step, name), None) for name, _ in wanted if name == 'u10' or step in offered]

    def decode(blob):
        step, name = blob
        grid = np.zeros((2, 2)) if name == 'u10' else np.array(per_step[step], dtype=float)
        return grid, LATS, LONS

    with mock.patch.object(build, 'plan_step', plan_step), \
            mock.patch.object(build, 'download_all', lambda plan, workers: {n: url for n, url, _ in plan}), \
            mock.patch.object(build, 'decode', decode), \
            mock.patch.object(build, 'subset', lambda grid, lats, lons: (grid, lats, lons)), \
            warnings.catch_warnings(), np.errstate(all='raise'):
        warnings.simplefilter('error')
        cubes = build.fetch_model(model(), CYCLE, workers=4, log=logs.append)[3]
    return cubes['precipitation'], [line for line in logs if 'downloaded and decoded' not in line]


def codes(cube_cell):
    return np.frombuffer(base64.b64decode(quantize(cube_cell, PRECIP.scale)), dtype='<i2').tolist()


def same(actual, expected):
    return np.allclose(np.asarray(actual, float), np.asarray(expected, float), rtol=0, atol=1e-9, equal_nan=True)


class InitialAccumulationTests(unittest.TestCase):
    def test_initial_missing_accumulation_stays_missing(self):
        # decoded NaN, raw sentinel -1 and raw sentinel 9999 at step 0; a valid zero cell beside them
        step0 = [[NAN, -1.0], [9999.0, 0.0]]
        cube, logs = fetch({0: step0, 3: [[0.003] * 2] * 2, 6: [[0.006] * 2] * 2})
        self.assertEqual(logs, ['ecmwf_ifs025 precipitation: 2 values out of range set missing'])
        for cell in ((0, 0), (0, 1), (1, 0)):
            self.assertTrue(same(cube[:, cell[0], cell[1]], [NAN, NAN, 1.0]), cell)
            self.assertEqual(codes(cube[:, cell[0], cell[1]]), [MISSING, MISSING, 100], cell)
        self.assertTrue(same(cube[:, 1, 1], VALID_RATE))
        self.assertEqual(codes(cube[:, 1, 1]), [0, 100, 100])

    def test_first_step_absent_from_the_index_stays_missing(self):
        cube, logs = fetch({3: [[0.003] * 2] * 2, 6: [[0.006] * 2] * 2}, offered=(3, 6))
        self.assertEqual(logs, ['ecmwf_ifs025 precipitation: missing at 1 of 3 steps'])
        self.assertTrue(np.isnan(cube[0]).all() and np.isnan(cube[1]).all())
        self.assertEqual(codes(cube[:, 0, 0]), [MISSING, MISSING, 100])

    def test_initial_infinity_is_not_a_dry_interval(self):
        for bad in (INF, -INF):
            with self.subTest(bad=bad):
                cube, logs = fetch({0: [[bad, 0.0]] * 2, 3: [[0.003] * 2] * 2, 6: [[0.006] * 2] * 2})
                self.assertEqual(logs, [])
                self.assertEqual(codes(cube[:, 0, 0]), [MISSING, MISSING, 100])
                self.assertEqual(codes(cube[:, 0, 1]), [0, 100, 100])

    def test_interior_infinity_is_missing_for_both_adjacent_intervals(self):
        cube, _ = fetch({0: [[0.0] * 2] * 2, 3: [[INF, 0.003]] * 2, 6: [[0.006] * 2] * 2})
        self.assertEqual(codes(cube[:, 0, 0]), [0, MISSING, MISSING])
        self.assertEqual(codes(cube[:, 0, 1]), [0, 100, 100])


class NonfiniteEndpointTests(unittest.TestCase):
    def test_nonfinite_endpoints_never_become_dry_intervals(self):
        for bad in (NAN, INF, -INF):
            for at in range(3):
                with self.subTest(bad=bad, at=at):
                    values = list(VALID)
                    values[at] = bad
                    expected = list(VALID_RATE)
                    expected[at] = NAN                       # the interval ending at the bad endpoint
                    if at + 1 < 3:
                        expected[at + 1] = NAN               # the interval starting at it
                    self.assertTrue(same(rates(values), expected), rates(values))

    def test_unaffected_intervals_recover_after_a_gap(self):
        values = [0.0, NAN, 0.006, 0.009]
        self.assertTrue(same(convert(ECMWF, 'precipitation', accumulated(values), [0, 3600 * 3, 3600 * 6, 3600 * 9])[:, 0, 0],
                             [0.0, NAN, NAN, 1.0]))


class CellValidityTests(unittest.TestCase):
    def test_mixed_cell_validity_is_not_global(self):
        cube = np.array([[[0.0, NAN], [0.0, 0.0]],
                         [[0.003, 0.003], [INF, 0.0]],
                         [[0.006, 0.006], [0.006, 0.003]]])
        before = cube.copy()
        with warnings.catch_warnings(), np.errstate(all='raise'):
            warnings.simplefilter('error')
            rate = convert(ECMWF, 'precipitation', cube, TIMES)
        self.assertTrue(same(rate[:, 0, 0], VALID_RATE))
        self.assertTrue(same(rate[:, 0, 1], [NAN, NAN, 1.0]))
        self.assertTrue(same(rate[:, 1, 0], [0.0, NAN, NAN]))
        self.assertTrue(same(rate[:, 1, 1], [0.0, 0.0, 1.0]))
        self.assertTrue(np.array_equal(cube, before, equal_nan=True), 'the input cube must not be modified')


class UnchangedBehaviourTests(unittest.TestCase):
    def test_valid_accumulation_semantics_are_unchanged(self):
        self.assertTrue(same(rates(VALID), VALID_RATE))
        self.assertTrue(same(rates([0.0, 0.003, 0.003]), [0.0, 1.0, 0.0]))        # equal values: dry interval
        self.assertTrue(same(rates([0.0, 0.003, 0.001]), [0.0, 1.0, 0.0]))        # a finite decrease is clamped
        two = convert(ECMWF, 'precipitation', accumulated([0.0, 0.003, 0.009]), [0, 3 * 3600, 9 * 3600])
        self.assertTrue(same(two[:, 0, 0], [0.0, 1.0, 1.0]))                      # 3 h then 6 h intervals
        one = convert(ECMWF, 'precipitation', accumulated([0.004]), [0])
        self.assertTrue(same(one[:, 0, 0], [0.0]))                                # initial finite convention

    def test_other_conversion_modes_are_unchanged(self):
        cube = np.array([[[1.0, NAN]], [[2.0, 3.0]]])
        by_field = {'t2m': lambda c: c - 273.15, 'cloud_cover': lambda c: c * 100.0, 'u10': lambda c: c}
        for name, fn in by_field.items():
            with self.subTest(name=name):
                self.assertTrue(same(convert(ECMWF, name, cube, [0, 3600]), fn(cube)))
        gfs = MODELS['gfs_global']
        self.assertTrue(same(convert(gfs, 'precipitation', cube, [0, 3600]), cube * 3600.0))


if __name__ == '__main__':
    unittest.main()

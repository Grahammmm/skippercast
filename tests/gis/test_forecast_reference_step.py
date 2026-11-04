"""Forecast tiles: the reference grid comes from the first step that offers the reference field."""
from contextlib import contextmanager
from datetime import datetime, timezone
import unittest
from unittest import mock

import numpy as np

from skippercast.forecast import build
from skippercast.forecast.models import Field, Model

CYCLE = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
LATS, LONS = np.array([34.0, 35.0]), np.array([-121.0, -120.0])
LATS3, LONS3 = np.array([34.0, 34.5, 35.0]), np.array([-121.0, -120.5, -120.0])
FINE = (LATS3, LONS3)
COARSE = (LATS, LONS)
SHIFTED = (np.array([34.5, 35.5]), np.array([-120.5, -119.5]))
STEPS = (0, 1, 2)
PLAIN = (Field('a', ('A', 'surface'), 0.01), Field('b', ('B', 'surface'), 0.01))
NATIVE = (Field('a', ('A', 'surface'), 0.01), Field('b', ('B', 'surface', 'native'), 0.01))


def model_with(fields):
    return Model(id='fake_model', name='Fake', provider='Test', kind='wind', family='gfs', cycles=(0, 12),
                 steps=STEPS, fields=fields, resolution_km=1, documentation='https://example.invalid')


@contextmanager
def serving(offered, grid_of):
    """offered: {step: names}; grid_of(step, name) -> (lats, lons) the decoded grid sits on. Values step*10 + 1 (a) / 2 (b)."""
    def plan_step(model, cycle, step, wanted):
        return [(name, (step, name), None) for name, _ in wanted if name in offered[step]]

    def decode(blob):
        step, name = blob
        lats, lons = grid_of(step, name)
        return np.full((len(lats), len(lons)), step * 10.0 + {'a': 1, 'b': 2}[name]), lats, lons

    with mock.patch.object(build, 'plan_step', plan_step), \
            mock.patch.object(build, 'download_all', lambda plan, workers: {n: url for n, url, _ in plan}), \
            mock.patch.object(build, 'decode', decode), \
            mock.patch.object(build, 'subset', lambda grid, lats, lons: (grid, lats, lons)):
        yield


class ReferenceStepTests(unittest.TestCase):
    def fetch(self, offered, grid_of, fields=PLAIN):
        logs = []
        with serving(offered, grid_of):
            result = build.fetch_model(model_with(fields), CYCLE, workers=4, log=logs.append)
        return result, [line for line in logs if 'downloaded and decoded' not in line]

    def test_first_field_missing_at_step_zero_takes_grid_from_step_one(self):
        offered = {0: {'b'}, 1: {'a', 'b'}, 2: {'a', 'b'}}
        grid_of = lambda step, name: SHIFTED if name == 'a' else COARSE  # noqa: E731
        (_, lats, lons, cubes, _), logs = self.fetch(offered, grid_of)
        self.assertEqual((lats.tolist(), lons.tolist()), (SHIFTED[0].tolist(), SHIFTED[1].tolist()))
        self.assertEqual(logs.count('fake_model a: reference grid from step 1'), 1)
        self.assertIn('fake_model a: missing at 1 of 3 steps', logs)
        self.assertEqual(len(logs), 2)
        self.assertTrue(np.isnan(cubes['a'][0]).all())
        self.assertEqual(cubes['a'][1:, 0, 0].tolist(), [11.0, 21.0])
        self.assertEqual(cubes['b'].shape, (3, 2, 2))
        self.assertFalse(np.isnan(cubes['b'][0]).all())  # b was regridded onto a's grid, not lost

    def test_native_field_missing_at_step_zero_only_is_the_reference_from_its_first_step(self):
        offered = {0: {'a'}, 1: {'a', 'b'}, 2: {'a', 'b'}}
        grid_of = lambda step, name: FINE if name == 'b' else COARSE  # noqa: E731
        (_, lats, lons, cubes, _), logs = self.fetch(offered, grid_of, NATIVE)
        self.assertEqual((lats.tolist(), lons.tolist()), (LATS3.tolist(), LONS3.tolist()))
        self.assertEqual(logs.count('fake_model b: reference grid from step 1'), 1)
        self.assertEqual(cubes['a'].shape, (3, 3, 3))  # the non-native field was regridded onto the native grid
        self.assertFalse(np.isnan(cubes['a']).any())
        self.assertTrue(np.isnan(cubes['b'][0]).all())
        self.assertEqual(cubes['b'][1:, 2, 2].tolist(), [12.0, 22.0])

    def test_reference_field_offered_at_no_step_keeps_the_named_failure(self):
        offered = {0: {'b'}, 1: {'b'}, 2: {'b'}}
        with self.assertRaises(ValueError) as caught:
            self.fetch(offered, lambda step, name: COARSE)
        self.assertEqual(str(caught.exception),
                         f"fake_model a: not offered at any step (index selector {PLAIN[0].select})")

    def test_reference_present_at_step_zero_is_unchanged_and_logs_no_reference_line(self):
        offered = {0: {'a', 'b'}, 1: {'a', 'b'}, 2: {'a', 'b'}}
        (_, lats, lons, cubes, _), logs = self.fetch(offered, lambda step, name: COARSE)
        self.assertEqual(logs, [])
        self.assertEqual((lats.tolist(), lons.tolist()), (LATS.tolist(), LONS.tolist()))
        self.assertEqual(cubes['a'][:, 0, 0].tolist(), [1.0, 11.0, 21.0])

    def test_reference_missing_only_at_step_zero_is_the_only_extra_log_when_others_are_complete(self):
        offered = {0: {'b'}, 1: {'a', 'b'}, 2: {'a', 'b'}}
        _, logs = self.fetch(offered, lambda step, name: COARSE)
        self.assertEqual(logs, ['fake_model a: missing at 1 of 3 steps', 'fake_model a: reference grid from step 1'])

    def test_a_later_step_on_a_different_shape_is_regridded_onto_the_reference(self):
        offered = {0: {'a', 'b'}, 1: {'a', 'b'}, 2: {'a', 'b'}}
        grid_of = lambda step, name: FINE if (name == 'b' and step == 2) else COARSE  # noqa: E731
        (_, lats, _, cubes, _), logs = self.fetch(offered, grid_of)
        self.assertEqual(lats.tolist(), LATS.tolist())
        self.assertEqual(cubes['b'].shape, (3, 2, 2))
        self.assertEqual(cubes['b'][2].tolist(), [[22.0, 22.0], [22.0, 22.0]])
        self.assertEqual(logs, [])

    def test_grid_that_is_still_off_the_reference_after_regridding_keeps_the_grid_changed_error(self):
        # regrid() always returns the reference shape, so the guard only fires if it misbehaves
        offered = {0: {'b'}, 1: {'a', 'b'}, 2: {'a', 'b'}}
        grid_of = lambda step, name: FINE if (name == 'b' and step == 2) else COARSE  # noqa: E731
        with mock.patch.object(build, 'regrid', lambda grid, *rest, **kw: np.zeros((1, 1))):
            with self.assertRaises(ValueError) as caught:
                self.fetch(offered, grid_of)
        self.assertEqual(str(caught.exception), 'fake_model b grid changed at step 2')


if __name__ == '__main__':
    unittest.main()

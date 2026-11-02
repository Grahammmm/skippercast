"""Forecast tiles: a field the index offers at no step fails that model by name; partial gaps are logged."""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from skippercast.forecast import build
from skippercast.forecast.models import Field, Model

CYCLE = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
LATS, LONS = np.array([34.0, 35.0]), np.array([-121.0, -120.0])
FIELDS = (Field('a', ('A', 'surface'), 0.01), Field('b', ('B', 'surface'), 0.01))
ORDER = {'__mask__': 0, 'a': 1, 'b': 2}
ALL = {s: {'a', 'b'} for s in (0, 1, 2)}


def fake_model(mask=()):
    return Model(id='fake_model', name='Fake', provider='Test', kind='wind', family='gfs', cycles=(0, 12),
                 steps=(0, 1, 2), fields=FIELDS, resolution_km=1, documentation='https://example.invalid', mask=mask)


@contextmanager
def index_offering(offered):
    """offered: {step: names the index has}; each grid is 2x2 valued step*10 + ORDER[name]. No network."""
    def plan_step(model, cycle, step, wanted):
        return [(name, (step, name), None) for name, _ in wanted if name in offered[step]]

    def decode(blob):
        step, name = blob
        return np.full((2, 2), step * 10.0 + ORDER[name]), LATS, LONS

    with mock.patch.object(build, 'plan_step', plan_step), \
            mock.patch.object(build, 'download_all', lambda plan, workers: {n: url for n, url, _ in plan}), \
            mock.patch.object(build, 'decode', decode), \
            mock.patch.object(build, 'subset', lambda grid, lats, lons: (grid, lats, lons)):
        yield


class FieldCoverageTests(unittest.TestCase):
    def run_fetch(self, offered, model=None):
        logs = []
        with index_offering(offered):
            result = build.fetch_model(model or fake_model(), CYCLE, workers=4, log=logs.append)
        return result, [line for line in logs if 'downloaded and decoded' not in line]

    def assert_named_failure(self, offered, field):
        with self.assertRaises(ValueError) as caught:
            self.run_fetch(offered)
        self.assertEqual(str(caught.exception), f"fake_model {field}: not offered at any step "
                                                f"(index selector {FIELDS[ORDER[field] - 1].select})")

    def test_field_absent_at_every_step_fails_the_model_by_name(self):
        self.assert_named_failure({0: {'a'}, 1: {'a'}, 2: {'a'}}, 'b')

    def test_reference_field_absent_everywhere_is_named_not_a_bare_key_error(self):
        self.assert_named_failure({0: {'b'}, 1: {'b'}, 2: {'b'}}, 'a')  # a KeyError would error, not pass

    def test_no_field_offered_anywhere_names_the_first(self):
        self.assert_named_failure({0: set(), 1: set(), 2: set()}, 'a')

    def test_field_missing_at_one_step_is_logged_and_that_step_is_nan(self):
        (_, _, _, cubes, _), logs = self.run_fetch({0: {'a', 'b'}, 1: {'a'}, 2: {'a', 'b'}})
        self.assertEqual(logs, ['fake_model b: missing at 1 of 3 steps'])
        self.assertTrue(np.isnan(cubes['b'][1]).all())
        self.assertEqual(cubes['b'][[0, 2], 0, 0].tolist(), [2.0, 22.0])
        self.assertFalse(np.isnan(cubes['a']).any())

    def test_field_present_only_at_last_step_is_logged_not_failed(self):
        (_, _, _, cubes, _), logs = self.run_fetch({0: {'a'}, 1: {'a'}, 2: {'a', 'b'}})
        self.assertEqual(logs, ['fake_model b: missing at 2 of 3 steps'])
        self.assertTrue(np.isnan(cubes['b'][:2]).all())
        self.assertEqual(cubes['b'][2, 0, 0], 22.0)

    def test_all_fields_present_logs_nothing_extra_and_cubes_unchanged(self):
        (times, lats, lons, cubes, sea), logs = self.run_fetch(ALL)
        self.assertEqual(logs, [])
        self.assertEqual(times, [int(CYCLE.timestamp()) + 3600 * s for s in (0, 1, 2)])
        self.assertEqual((lats.tolist(), lons.tolist()), (LATS.tolist(), LONS.tolist()))
        self.assertEqual(cubes['a'][:, 0, 0].tolist(), [1.0, 11.0, 21.0])
        self.assertEqual(cubes['b'][:, 1, 1].tolist(), [2.0, 12.0, 22.0])
        self.assertTrue(sea.all())

    def test_mask_model_with_mask_missing_keeps_its_own_error(self):
        with self.assertRaises(ValueError) as caught:
            self.run_fetch(ALL, fake_model(mask=('LAND', 'surface')))
        self.assertEqual(str(caught.exception), 'fake_model land-sea mask missing')

    def test_mask_model_with_mask_present_builds(self):
        offered = {0: {'a', 'b', '__mask__'}, 1: {'a', 'b'}, 2: {'a', 'b'}}
        (_, _, _, _, sea), logs = self.run_fetch(offered, fake_model(mask=('LAND', 'surface')))
        self.assertEqual(logs, [])
        self.assertTrue(sea.all())  # mask value 0.0 < 0.5 is sea

    def test_build_reports_the_named_failure_and_publishes_nothing_for_that_model(self):
        model = fake_model()
        with tempfile.TemporaryDirectory() as directory, index_offering({0: {'a'}, 1: {'a'}, 2: {'a'}}), \
                mock.patch.dict(build.MODELS, {model.id: model}), \
                mock.patch.object(build, 'latest_cycle', lambda m: CYCLE):
            index = build.build(Path(directory), models=[model.id], log=lambda message: None)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['index.json'])
        row = index['models'][model.id]
        self.assertEqual((row['status'], row['kept_previous']), ('failed', False))
        self.assertIn("fake_model b: not offered at any step (index selector ('B', 'surface'))", row['issue'])


@contextmanager
def serving(grids):
    """grids: {name: [2x2 grid per step]}; every field is offered at every step. No network."""
    with mock.patch.object(build, 'plan_step', lambda m, c, step, wanted: [(n, (step, n), None) for n, _ in wanted]), \
            mock.patch.object(build, 'download_all', lambda plan, workers: {n: url for n, url, _ in plan}), \
            mock.patch.object(build, 'decode', lambda blob: (np.array(grids[blob[1]][blob[0]], float), LATS, LONS)), \
            mock.patch.object(build, 'subset', lambda grid, lats, lons: (grid, lats, lons)):
        yield


def ranged_model(fields, steps=(0, 1, 2, 3)):
    return Model(id='fake_model', name='Fake', provider='Test', kind='wave', family='gfs', cycles=(0, 12),
                 steps=steps, fields=fields, resolution_km=1, documentation='https://example.invalid')


def bounded(model_id, name, cube):
    logs = []
    return build.bound(build.MODELS[model_id], name, np.array(cube, float), logs.append), logs


class RangeTests(unittest.TestCase):
    def fetch(self, fields, grids):
        logs = []
        with serving(grids):
            _, _, _, cubes, _ = build.fetch_model(ranged_model(fields), CYCLE, workers=4, log=logs.append)
        return cubes, [line for line in logs if 'downloaded and decoded' not in line]

    def test_sentinel_without_bitmap_becomes_missing_and_is_counted_in_the_build_log(self):
        grid = [[1.5, 9999.0], [2.0, 0.5]]
        cubes, logs = self.fetch((Field('swell_wave_height', ('SWELL', '1 in sequence'), 0.01),),
                                 {'swell_wave_height': [grid] * 4})
        self.assertEqual(logs, ['fake_model swell_wave_height: 4 values out of range set missing'])
        self.assertTrue(np.isnan(cubes['swell_wave_height'][:, 0, 1]).all())
        self.assertEqual(cubes['swell_wave_height'][0].ravel()[[0, 2, 3]].tolist(), [1.5, 2.0, 0.5])
        q = np.frombuffer(base64.b64decode(build.quantize(cubes['swell_wave_height'], 0.01)), '<i2').reshape(4, 2, 2)
        self.assertEqual(q[:, 0, 1].tolist(), [build.MISSING] * 4)
        self.assertEqual(q[0, 0, 0], 150)

    def test_one_sentinel_cell_logs_one(self):
        cube, logs = bounded('ncep_gfswave016', 'swell_wave_height', [[[1.0, 9999.0]]])
        self.assertTrue(np.isnan(cube[0, 0, 1]))
        self.assertEqual(logs, ['ncep_gfswave016 swell_wave_height: 1 values out of range set missing'])

    def test_boundary_values_are_kept(self):
        for name, edges in (('wave_height', [0, 30]), ('wave_direction', [0, 360]), ('wave_period', [0, 40])):
            cube, logs = bounded('ncep_gfswave016', name, edges)
            self.assertEqual((cube.tolist(), logs), (edges, []), name)
        cube, logs = bounded('gfs_global', 'cloud_cover', [0, 100])
        self.assertEqual((cube.tolist(), logs), ([0, 100], []))
        gfs = build.MODELS['gfs_global']
        celsius = build.convert(gfs, 't2m', np.array([183.15, 333.15]), [0, 3600])
        self.assertEqual(np.round(build.bound(gfs, 't2m', celsius, self.fail), 6).tolist(), [-90.0, 60.0])

    def test_just_outside_the_bounds_is_dropped(self):
        cube, logs = bounded('ncep_gfswave016', 'wave_direction', [-0.1, 360.1, 180])
        self.assertTrue(np.isnan(cube[:2]).all())
        self.assertEqual(logs, ['ncep_gfswave016 wave_direction: 2 values out of range set missing'])

    def test_t2m_sentinel_kelvin_is_missing_after_conversion(self):
        gfs, logs = build.MODELS['gfs_global'], []
        celsius = build.convert(gfs, 't2m', np.array([9999.0, 288.15]), [0, 3600])
        cube = build.bound(gfs, 't2m', celsius, logs.append)
        self.assertTrue(np.isnan(cube[0]))
        self.assertAlmostEqual(cube[1], 15.0)
        self.assertEqual(logs, ['gfs_global t2m: 1 values out of range set missing'])

    def test_accumulated_sentinel_never_becomes_a_huge_rate(self):
        steps = [[[0.0, 0.0], [0.0, 0.0]], [[0.002, 0.0], [0.0, 0.0]], [[9999.0, 0.0], [0.0, 0.0]],
                 [[0.005, 0.0], [0.0, 0.0]]]
        cubes, logs = self.fetch((Field('precipitation', ('tp',), 0.01, 'accumulated_m'),), {'precipitation': steps})
        rate = cubes['precipitation'][:, 0, 0]
        self.assertAlmostEqual(rate[1], 2.0)
        self.assertTrue(np.isnan(rate[2:]).all())
        self.assertLess(np.nanmax(cubes['precipitation']), 500)
        self.assertEqual(cubes['precipitation'][:, 1, 1].tolist(), [0.0] * 4)
        self.assertEqual(logs, ['fake_model precipitation: 1 values out of range set missing'])

    def test_negative_gust_and_period_dropped_negative_wind_component_kept(self):
        for model_id, name in (('gfs_global', 'gust'), ('ncep_gfswave016', 'wave_period')):
            cube, logs = bounded(model_id, name, [-1.0, 5.0])
            self.assertTrue(np.isnan(cube[0]), name)
            self.assertEqual(logs, [f'{model_id} {name}: 1 values out of range set missing'])
        cube, logs = bounded('gfs_global', 'u10', [-20.0, 101.0])
        self.assertEqual(cube[0], -20.0)
        self.assertTrue(np.isnan(cube[1]))

    def test_nan_cells_are_not_counted_and_in_range_logs_nothing(self):
        cube, logs = bounded('ncep_gfswave016', 'wave_height', [np.nan, 2.0, np.nan])
        self.assertEqual((np.isnan(cube).tolist(), logs), ([True, False, True], []))
        cube, logs = bounded('ncep_gfswave016', 'wave_height', [np.nan, 99.0])
        self.assertEqual(logs, ['ncep_gfswave016 wave_height: 1 values out of range set missing'])
        cubes, logs = self.fetch((Field('wave_height', ('HTSGW', 'surface'), 0.01),),
                                 {'wave_height': [[[np.nan, 1.0], [2.0, 3.0]]] * 4})
        self.assertEqual(logs, [])

    def test_every_model_field_has_a_range(self):
        missing = [(m.id, f.name) for m in build.MODELS.values() for f in m.fields if f.name not in build.RANGES]
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()

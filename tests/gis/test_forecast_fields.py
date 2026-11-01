"""Forecast tiles: a field the index offers at no step fails that model by name; partial gaps are logged."""
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


if __name__ == '__main__':
    unittest.main()

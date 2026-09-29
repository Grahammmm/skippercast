"""Forecast tile builder: index parsing, grids, quantization, and agreement with the JS sampler."""
from datetime import datetime, timezone
import base64
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from skippercast.forecast import fetch, local
from skippercast.forecast.build import MISSING, convert, manifest_for, quantize, regrid, subset, write_tiles
from skippercast.forecast.models import MODELS

GFS_IDX = """1:0:d=2026092718:PRMSL:mean sea level:24 hour fcst:
2:100:d=2026092718:PRATE:surface:18-24 hour ave fcst:
3:250:d=2026092718:PRATE:surface:24 hour fcst:
4:400:d=2026092718:SWELL:1 in sequence:24 hour fcst:
5:500:d=2026092718:SWELL:2 in sequence:24 hour fcst:
"""


class IndexTests(unittest.TestCase):
    def test_gfs_selects_instantaneous_fields_and_open_ended_last_message(self):
        rows = fetch.parse_gfs_idx(GFS_IDX)
        self.assertEqual(fetch.select_gfs(rows, 'PRATE', 'surface'), (250, 399))
        self.assertEqual(fetch.select_gfs(rows, 'SWELL', '2 in sequence'), (500, None))
        self.assertIsNone(fetch.select_gfs(rows, 'GUST', 'surface'))

    def test_ecmwf_index_and_alternative_parameter_names(self):
        text = '\n'.join(json.dumps(r) for r in [
            {'param': '10u', 'levtype': 'sfc', '_offset': 0, '_length': 10},
            {'param': '10fg3', 'levtype': 'sfc', '_offset': 10, '_length': 5},
            {'param': 'gh', 'levtype': 'pl', 'levelist': '500', '_offset': 15, '_length': 5}])
        index = fetch.parse_ecmwf_index(text)
        self.assertEqual(index['10fg3'], (10, 14))
        self.assertNotIn('gh', index)
        gust = MODELS['ecmwf_ifs025'].field('gust').select
        self.assertEqual(next(index[p] for p in gust if p in index), (10, 14))

    def test_ecmwf_hosts_mirror_each_other(self):
        aws = fetch.ecmwf_url(MODELS['ecmwf_wam'], datetime(2026, 9, 27, 12, tzinfo=timezone.utc), 24)
        self.assertTrue(fetch.mirror(aws).startswith(fetch.ECMWF_PORTAL + '/20260927/12z/ifs/0p25/wave/'))
        self.assertEqual(fetch.mirror(fetch.mirror(aws)), aws)
        self.assertIsNone(fetch.mirror('https://example.com/x'))


class GridTests(unittest.TestCase):
    def test_subset_wraps_0_360_longitudes_and_orders_south_to_north(self):
        lats = np.arange(-90, 90.25, 0.25)
        lons = (np.arange(0, 360, 0.25) + 180) % 360 - 180
        grid = np.add.outer(lats, lons)
        sub, slats, slons = subset(grid, lats, lons)
        self.assertLess(slats[0], 32)
        self.assertGreater(slats[-1], 43)
        self.assertTrue(np.all(np.diff(slons) > 0))
        self.assertAlmostEqual(sub[0, 0], slats[0] + slons[0])

    def test_regrid_bilinear_and_nearest(self):
        lats, lons = np.array([0., 1.]), np.array([0., 1.])
        grid = np.array([[0., 1.], [2., 3.]])
        self.assertAlmostEqual(regrid(grid, lats, lons, np.array([.5]), np.array([.5]))[0, 0], 1.5)
        self.assertEqual(regrid(grid, lats, lons, np.array([.9]), np.array([.1]), nearest=True)[0, 0], 2.)

    def test_accumulated_precipitation_becomes_hourly_rate(self):
        times = [0, 3 * 3600, 6 * 3600]
        acc = np.array([0., 0.003, 0.003]).reshape(3, 1, 1)  # metres
        rate = convert(MODELS['ecmwf_ifs025'], 'precipitation', acc, times)
        self.assertEqual(rate[:, 0, 0].tolist(), [0.0, 1.0, 0.0])

    def test_quantize_round_trip_and_missing(self):
        raw = np.frombuffer(base64.b64decode(quantize(np.array([1.234, np.nan, -2.0]), 0.01)), '<i2')
        self.assertEqual(raw.tolist(), [123, MISSING, -200])


@unittest.skipUnless(shutil.which('node'), 'Node is needed for the shared sampler')
class SamplerAgreementTests(unittest.TestCase):
    """Tiles written by Python, read back through the JavaScript sampler."""

    def test_python_tiles_sample_exactly_at_grid_cells(self):
        model = MODELS['ncep_gfswave016']
        cycle = datetime(2026, 9, 27, tzinfo=timezone.utc)
        lats = np.arange(34.5, 36.51, 1 / 6)
        lons = np.arange(-122.5, -119.49, 1 / 6)
        times = [int(cycle.timestamp()) + 3600 * h for h in (0, 1, 2)]
        shape = (len(times), len(lats), len(lons))
        cubes = {f.name: np.full(shape, np.nan) for f in model.fields}
        cubes['wave_height'] = np.broadcast_to(np.array([1., 2., 3.])[:, None, None], shape).copy()
        cubes['wave_direction'] = np.full(shape, 300.)
        sea = np.ones((len(lats), len(lons)), bool)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keys = write_tiles(model, cycle, times, lats, lons, cubes, sea, root / model.id)
            self.assertIn('35_-121', keys)
            manifest = manifest_for(model, cycle, times, keys, lats, lons, cycle, 1)
            (root / model.id / 'manifest.json').write_text(json.dumps(manifest))
            (root / 'index.json').write_text('{}')
            result = local.run_sampler(root, 'marine', 'latitude=35.5&longitude=-120.5&models=ncep_gfswave016'
                                       '&hourly=wave_height,wave_direction&timezone=UTC&timeformat=unixtime&forecast_days=1', now=times[0])
        hours = result['hourly']['time']
        heights = dict(zip(hours, result['hourly']['wave_height']))
        self.assertEqual([heights[t] for t in times], [1.0, 2.0, 3.0])
        self.assertEqual(result['hourly']['wave_direction'][0], 300)
        self.assertEqual(manifest['meta']['last_run_initialisation_time'], times[0])


if __name__ == '__main__':
    unittest.main()

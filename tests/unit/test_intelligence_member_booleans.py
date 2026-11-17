"""Boolean GEFS member samples are unavailable, never 0/1 m/s measurements."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skippercast.pipeline.intelligence import _member_value, ensemble

CYCLE = 1790467200
TIMES = [CYCLE + h * 3600 for h in (0, 3, 6)]


class MemberValueTests(unittest.TestCase):
    def test_native_boolean_members_are_unavailable(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                self.assertIsNone(_member_value([bad, 1, 1], TIMES[0], TIMES))
        for good in (0, 1, 0.0, 1.0):
            with self.subTest(good=good):
                self.assertEqual(_member_value([good, 5, 5], TIMES[0], TIMES), good)

    def test_boolean_interpolation_endpoint_is_unavailable(self):
        series = [2.0, True, 4.0]
        hour = CYCLE + 3600
        self.assertIsNone(_member_value(series, hour, TIMES))  # 0->3 needs the boolean
        self.assertIsNone(_member_value(series, TIMES[1] + 3600, TIMES))  # 3->6 needs it too
        self.assertEqual(_member_value(series, TIMES[0], TIMES), 2.0)  # exact good endpoints stay
        self.assertEqual(_member_value(series, TIMES[2], TIMES), 4.0)
        self.assertIsNone(_member_value(series, TIMES[1], TIMES))
        self.assertAlmostEqual(_member_value([2.0, 5.0, False], hour, TIMES), 3.0)  # not touching it


class EnsembleBooleanTests(unittest.TestCase):
    class Offline:
        def __init__(self):
            self.requests = []

        def get(self, *a, **k):
            raise AssertionError('local build must be read without the network')

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {'SKIPPERCAST_FORECAST_ROOT': str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.region = {'id': 'test-region', 'forecast_points': [{'id': 'a', 'latitude': 35.5, 'longitude': -121.5}, {'id': 'b', 'latitude': 35.0, 'longitude': -121.0}],
                       'intelligence': {'wind_ensemble_model': 'gfs025'}}

    def build(self, wind_override=None, gust_override=None):
        wind = [[0, 3, 6] for _ in range(31)]
        gust = [[1, 5, 8] for _ in range(31)]
        if wind_override:
            wind[0] = wind_override
        if gust_override:
            gust[0] = gust_override
        manifest = {'model': 'ncep_gefs025', 'sea_radius_km': 30, 'meta': {'last_run_initialisation_time': CYCLE, 'last_run_modification_time': CYCLE + 5 * 3600, 'data_end_time': TIMES[-1]},
                    'upstream': {'cycle_prefix': 'https://noaa-gefs-pds.s3.amazonaws.com/gefs.20260928/00/atmos/pgrb2sp25/', 'messages': 6045, 'messages_sha256': '0' * 64, 'missing': []}}
        region = {'cycle': CYCLE, 'times': TIMES, 'members': 31, 'units': {'wind_speed_10m': 'm/s', 'wind_gusts_10m': 'm/s'},
                  'points': [{'latitude': 35.5, 'longitude': -121.5, 'grid': [35.5, -121.5], 'distance_km': 0.0, 'wind_speed_10m': wind, 'wind_gusts_10m': gust},
                             {'latitude': 35.0, 'longitude': -121.0, 'grid': None, 'distance_km': None, 'wind_speed_10m': [[None] * 3] * 31, 'wind_gusts_10m': [[None] * 3] * 31}]}
        for relative, value in (('manifest.json', manifest), ('regions/test-region.json', region)):
            path = self.root / 'ncep_gefs025' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        return ensemble(self.Offline(), self.region)

    @staticmethod
    def ids(frame):
        return [m[0] for m in frame['members']]

    def test_ensemble_boolean_wind_omits_member(self):
        healthy = self.build()
        data = self.build(wind_override=[True, 3, 6])
        frames, base = data['points'][0]['frames'], healthy['points'][0]['frames']
        self.assertEqual(len(frames), 7)
        self.assertNotIn(0, self.ids(frames[0]))  # native hour 0 is boolean
        self.assertNotIn(0, self.ids(frames[1]))  # interpolation depends on it
        self.assertNotIn(0, self.ids(frames[2]))
        self.assertIn(0, self.ids(frames[3]))  # native good hour is available
        for i in (0, 1, 2):
            self.assertEqual([m for m in frames[i]['members']], [m for m in base[i]['members'] if m[0] != 0])
        self.assertEqual(frames[3:], base[3:])
        self.assertEqual(data['points'][1]['frames'], [])
        self.assertEqual(data['expected_members'], 31)

    def test_ensemble_boolean_gust_keeps_wind(self):
        healthy = self.build()
        data = self.build(gust_override=[True, 5, 8])
        frames, base = data['points'][0]['frames'], healthy['points'][0]['frames']
        first = dict((m[0], m[1:]) for m in frames[0]['members'])
        self.assertEqual(first[0], [0.0, None])  # wind kept, gust unavailable
        self.assertEqual(dict((m[0], m[1:]) for m in frames[1]['members'])[0][1], None)
        self.assertEqual(frames[3], base[3])
        for i in (0, 1):
            self.assertEqual([m for m in frames[i]['members'] if m[0] != 0], [m for m in base[i]['members'] if m[0] != 0])
            self.assertEqual(dict((m[0], m) for m in frames[i]['members'])[0][1], dict((m[0], m) for m in base[i]['members'])[0][1])
        self.assertEqual(data['points'][1]['frames'], [])


if __name__ == '__main__':
    unittest.main()

"""SP-10-v1: exercise real DAP parsing and HFR assembly using synthetic text only.

No target imports, environment changes or permanent audit hooks at collection.
The acceptance runner installs child-process guards before importing this module.
"""
import copy
from contextlib import ExitStack
import importlib
import json
import math
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/sp1010_hfr_quality/producer.json'
BASE = 'https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_6km'
FIELDS = ('u', 'v', 'hdop', 'number_of_sites')


class SyntheticDAP:
    """Four producer-shaped responses; never delegate an unknown request."""
    def __init__(self, fixture, frames, *, ny=1, nx=None, times=None):
        self.fixture = fixture
        self.frames = frames
        self.ny = ny
        self.nx = len(frames[0]) // ny if nx is None else nx
        self.times = (fixture['times'][:len(frames)] if times is None else times)
        if len(self.times) != len(frames) or any(len(f) != ny * self.nx for f in frames):
            raise ValueError('Invalid synthetic shape')
        self.lat = [fixture['latitude'] + i * fixture['coordinate_step'] for i in range(ny)]
        self.lon = [fixture['longitude'] + i * fixture['coordinate_step'] for i in range(self.nx)]
        self.requests = []

    @staticmethod
    def ascii(arrays):
        rows = ['Dataset { synthetic; }', '---------------------------------------------']
        for name, dimensions, values in arrays:
            rows += [name + ''.join(f'[{n}]' for n in dimensions),
                     '[0]' * max(1, len(dimensions) - 1) + ', ' + ', '.join(map(str, values))]
        return '\n'.join(rows) + '\n'

    def get(self, url):
        self.requests.append(url)
        if url == BASE + '.dds':
            return ('Dataset { Float64 time[time = %d]; Float64 lat[lat = %d]; '
                    'Float64 lon[lon = %d]; } synthetic;') % (len(self.times), self.ny, self.nx)
        if url == BASE + '.das':
            return self.fixture['das']
        if not url.startswith(BASE + '.ascii?'):
            raise AssertionError('Unexpected fake-client endpoint: ' + url)
        query = unquote(url.split('?', 1)[1])
        axes = re.fullmatch(r'time\[(\d+):1:(\d+)\],lat,lon', query)
        if axes:
            first, last = map(int, axes.groups())
            values = self.times[first:last + 1]
            return self.ascii([('time', [len(values)], values),
                               ('lat', [self.ny], self.lat), ('lon', [self.nx], self.lon)])
        parts = query.split(',')
        match = re.fullmatch(r'u\[(\d+):1:(\d+)\]\[(\d+):(\d+):(\d+)\]\[(\d+):(\d+):(\d+)\]', parts[0])
        if not match or len(parts) != 4:
            raise AssertionError('Unexpected DAP query: ' + query)
        suffix = parts[0][1:]
        if parts != [k + suffix for k in FIELDS]:
            raise AssertionError('Mismatched DAP field selection')
        t0, t1, y0, ys, y1, x0, xs, x1 = map(int, match.groups())
        ts, yy, xx = range(t0, t1 + 1), range(y0, y1 + 1, ys), range(x0, x1 + 1, xs)
        selected = [self.frames[t][y * self.nx + x] for t in ts for y in yy for x in xx]
        return self.ascii([(k + '.' + k, [len(ts), len(yy), len(xx)],
                            [c[k] for c in selected]) for k in FIELDS])


class RegressionTests(unittest.TestCase):
    def setUp(self):
        # Reversible guards also cover ordinary unittest/pytest discovery. They
        # end with each test and do not poison unrelated suites or the environment.
        stack = self.enterContext(ExitStack())
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.bind', 'socket.create_connection',
                       'socket.getaddrinfo', 'subprocess.Popen'):
            stack.enter_context(patch(target, side_effect=AssertionError('SP1010 offline-only')))
        self.ocean = importlib.import_module('skippercast.pipeline.ocean')
        self.assertEqual(Path(str(self.ocean.__file__)).resolve(), ROOT / 'src/skippercast/pipeline/ocean.py')
        self.fixture = json.loads(FIXTURE.read_text())

    def cell(self, **changes):
        return dict(self.fixture['defaults'], **changes)

    def run_hfr(self, frames, **shape):
        client = SyntheticDAP(self.fixture, copy.deepcopy(frames), **shape)
        result = self.ocean.hfr(client, self.fixture['region'])
        self.assertEqual(len(client.requests), 4)
        self.assertEqual(client.requests[:2], [BASE + '.dds', BASE + '.das'])
        self.assertEqual(result['source_url'], BASE + '.html')
        self.assertEqual(result['fields'], ['latitude', 'longitude', 'speed_knots',
                                          'toward_degrees', 'hdop', 'radar_count'])
        self.assertEqual(result['kind'], 'observation')
        self.assertTrue(result['surface_only'])
        self.assertEqual(result['resolution_km'], 6)
        self.assertEqual(result['limitations'], 'Observed near-surface flow; local gaps retained. Not boat drift or bottom current. HDOP <=2 and at least two contributing radars.')
        return result, client

    def assert_empty(self, result):
        self.assertEqual(result['valid_cells'], 0)
        self.assertIsNone(result['sample_at'])
        self.assertTrue(result['frames'])
        for frame in result['frames']:
            self.assertEqual(frame['cells'], [])
            self.assertEqual(frame['valid_cells'], 0)
            self.assertEqual(frame['total_cells'], result['total_cells'])
        json.dumps(result, allow_nan=False)

    def test_primary_regression(self):
        # A4: product exceptions become observed data before the semantic
        # assertion; they must never be accepted as harness/import errors.
        try:
            observed, _ = self.run_hfr([[self.cell(hdop='NaN')]])
        except (ValueError, OverflowError) as error:
            observed = {'product_exception': type(error).__name__ + ': ' + str(error)}
        self.assertEqual(observed.get('valid_cells'), 0, 'A1 NaN must be excluded: ' + repr(observed))
        self.assert_empty(observed)
        self.assertEqual(observed['latest_grid_time'], '2023-11-14T22:13:20Z')

    def test_healthy_control(self):
        result, _ = self.run_hfr([[self.cell()]])
        self.assertEqual(result['valid_cells'], 1)
        self.assertEqual(result['frames'], [{'time': 1700000000,
                         'cells': [[35.0, -121.0, 1.944, 90.0, 1.0, 2]],
                         'valid_cells': 1, 'total_cells': 1}])
        self.assertEqual(result['sample_at'], '2023-11-14T22:13:20Z')
        self.assertEqual(result['latest_grid_time'], result['sample_at'])
        self.assertTrue(math.isfinite(result['frames'][0]['cells'][0][4]))
        json.dumps(result, allow_nan=False)

    def test_each_invalid_hdop_isolated(self):
        for value in self.fixture['invalid_hdop']:
            with self.subTest(packed_hdop=value):
                result, _ = self.run_hfr([[self.cell(hdop=value)]])
                self.assert_empty(result)
                self.assertEqual(result['total_cells'], 1)

    def test_mixed_cells_keep_exact_identities_and_counts(self):
        values = ['NaN', '0', 'Infinity', '100', '-Infinity', '-1', '200', '200.0001']
        result, _ = self.run_hfr([[self.cell(hdop=h) for h in values]])
        self.assertEqual(result['frames'][0]['cells'], [
            [35.0, -120.999, 1.944, 90.0, 0.0, 2],
            [35.0, -120.997, 1.944, 90.0, 1.0, 2],
            [35.0, -120.994, 1.944, 90.0, 2.0, 2]])
        self.assertEqual(result['valid_cells'], 3)
        self.assertEqual(result['frames'][0]['valid_cells'], 3)
        self.assertEqual(result['total_cells'], 8)
        self.assertEqual(result['frames'][0]['total_cells'], 8)
        json.dumps(result, allow_nan=False)

    def test_finite_endpoints_and_nearby_values_keep_scale(self):
        result, _ = self.run_hfr([[self.cell(hdop=h) for h in self.fixture['finite_hdop']]])
        self.assertEqual([c[4] for c in result['frames'][0]['cells']], [0.0, 0.0, 0.01, 1.0, 2.0, 2.0])
        self.assertEqual(result['valid_cells'], 6)
        self.assertEqual([c[1] for c in result['frames'][0]['cells']],
                         [-121.0, -120.999, -120.998, -120.997, -120.996, -120.995])
        self.assertTrue(all(c[2:4] == [1.944, 90.0] and c[5] == 2 for c in result['frames'][0]['cells']))
        json.dumps(result, allow_nan=False)

    def test_existing_radar_count_gates(self):
        result, _ = self.run_hfr([[self.cell(number_of_sites=n) for n in self.fixture['radar_counts']]])
        self.assertEqual(result['frames'][0]['cells'], [
            [35.0, -120.997, 1.944, 90.0, 1.0, 2],
            [35.0, -120.996, 1.944, 90.0, 1.0, 20]])
        self.assertEqual(result['valid_cells'], 2)
        json.dumps(result, allow_nan=False)

    def test_existing_sentinel_and_vector_validation(self):
        invalid = [self.cell(u='-32767'), self.cell(v='-32767'), self.cell(u='NaN'),
                   self.cell(v='Infinity'), self.cell(u='501'), self.cell(v='-501')]
        result, _ = self.run_hfr([invalid + [self.cell(u='0', v='0'), self.cell(u='0', v='-100')]])
        self.assertEqual(result['frames'][0]['cells'], [
            [35.0, -120.994, 0.0, 0.0, 1.0, 2],
            [35.0, -120.993, 1.944, 180.0, 1.0, 2]])
        self.assertEqual(result['valid_cells'], 2)
        json.dumps(result, allow_nan=False)

    def test_all_empty_frames_retain_latest_grid(self):
        result, _ = self.run_hfr([[self.cell(hdop='NaN')], [self.cell(hdop='Infinity')]])
        self.assert_empty(result)
        self.assertEqual([f['time'] for f in result['frames']], [1700000000, 1700003600])
        self.assertEqual(result['latest_grid_time'], '2023-11-14T23:13:20Z')

    def test_latest_empty_frame_does_not_replace_last_observation(self):
        result, _ = self.run_hfr([[self.cell()], [self.cell(hdop='NaN')]])
        self.assertEqual(result['sample_at'], '2023-11-14T22:13:20Z')
        self.assertEqual(result['latest_grid_time'], '2023-11-14T23:13:20Z')
        self.assertEqual(result['valid_cells'], 1)
        self.assertEqual(result['frames'][1]['cells'], [])
        self.assertEqual(result['frames'][1]['valid_cells'], 0)
        json.dumps(result, allow_nan=False)

    def test_grid_stride_and_regional_selection_unchanged(self):
        result, client = self.run_hfr([[self.cell() for _ in range(35 * 35)]], ny=35)
        self.assertEqual(result['grid_stride'], 2)
        self.assertEqual(result['total_cells'], 18 * 18)
        self.assertEqual(result['valid_cells'], 18 * 18)
        self.assertEqual(result['frames'][0]['cells'][0][:2], [35.0, -121.0])
        self.assertEqual(result['frames'][0]['cells'][-1][:2], [35.034, -120.966])
        self.assertIn('u[0:1:0][0:2:34][0:2:34]', unquote(client.requests[-1]))

    def test_time_selection_keeps_six_frames_and_gaps(self):
        frames = [[self.cell(hdop='NaN' if i in (2, 7) else '100')] for i in range(8)]
        times = [1700000000 + i * 3600 for i in range(8)]
        result, client = self.run_hfr(frames, times=times)
        self.assertEqual([f['time'] for f in result['frames']], times[2:])
        self.assertEqual([f['valid_cells'] for f in result['frames']], [0, 1, 1, 1, 1, 0])
        self.assertEqual(result['frames'][0]['cells'], [])
        self.assertEqual(result['frames'][-1]['cells'], [])
        self.assertEqual(result['valid_cells'], 1)
        self.assertIn('time[2:1:7],lat,lon', unquote(client.requests[2]))
        json.dumps(result, allow_nan=False)

    def test_real_dap_arrays_and_dap_preserve_quality_tokens(self):
        client = SyntheticDAP(self.fixture, [[self.cell(hdop='NaN'), self.cell(hdop='100')]])
        query = ','.join(k + '[0:1:0][0:1:0][0:1:1]' for k in FIELDS)
        text = client.get(BASE + '.ascii?' + query)
        parsed = self.ocean.dap_arrays(text)
        self.assertTrue(math.isnan(parsed['hdop.hdop'][0]))
        self.assertEqual(parsed['hdop.hdop'][1], 100.0)
        through_dap = self.ocean.dap(client, BASE, query)
        self.assertTrue(math.isnan(through_dap['hdop.hdop'][0]))
        self.assertEqual(through_dap['hdop.hdop'][1], 100.0)
        self.assertEqual(through_dap['number_of_sites.number_of_sites'], [2.0, 2.0])

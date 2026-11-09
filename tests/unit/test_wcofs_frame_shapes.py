"""RF0854-5: ocean.wcofs() checks every spatial array against the requested grid size, so equally truncated or
oversized arrays are refused (failed/retained source) while a complete all-dry grid stays 'missing'.
Synthetic in-memory DAP replies; offline."""
from datetime import datetime, timezone
import unittest
from skippercast.pipeline.collect import source
from skippercast.pipeline.ocean import wcofs

NOW = datetime(2026, 11, 1, 22, tzinfo=timezone.utc)
REGION = {'bounds': [-121.20, 35.08, -120.64, 35.64]}  # rows 417..430, columns 605..618: 14 x 14 = 196 cells
N, WET, FILL = 196, 112, -99999.0
CYCLE = datetime(2026, 11, 1, 3, tzinfo=timezone.utc)
ORIGIN = datetime(2016, 1, 1, tzinfo=timezone.utc)
FILES = ['wcofs.t03z.20261101.regulargrid.f018.nc', 'wcofs.t03z.20261101.regulargrid.f021.nc']
SPATIAL = ('Latitude', 'Longitude', 'mask', 'u_eastward', 'v_northward')


def axis(name, at_index, value, n):
    return f'{name}[{n}][1]\n' + ', '.join(str(round(value + (i - at_index) * 0.04, 6)) for i in range(n)) + '\n'


def arrays(wet=WET, filename=FILES[0]):
    hours = int(filename.split('.f')[1][:3])
    seconds = (CYCLE.timestamp() - ORIGIN.timestamp()) + hours * 3600
    return {'Latitude': [35.1 + 0.04 * (i // 14) for i in range(N)], 'Longitude': [-121.18 + 0.04 * (i % 14) for i in range(N)],
            'mask': [1.0 if i < wet else 0.0 for i in range(N)],
            'u_eastward': [0.1 if i < wet else FILL for i in range(N)], 'v_northward': [0.05 if i < wet else FILL for i in range(N)],
            'time': [seconds]}


def body(data):
    return 'Dataset { } x;\n' + '-' * 45 + '\n' + ''.join(
        f'{key}[{len(values)}]\n' + ', '.join(repr(v) for v in values) + '\n' for key, values in data.items())


class Client:
    def __init__(self, bodies=None):
        self.bodies = bodies or {name: body(arrays(filename=name)) for name in FILES}
        self.requests = []

    def get(self, url):
        self.requests.append(url)
        if url.endswith('catalog.xml'):
            return ''.join(f'<dataset name="{n}" urlPath="NOAA/WCOFS/MODELS/2026/11/01/{n}"/>' for n in FILES)
        if url.endswith('.dds'):
            return 'Dataset { Float64 Latitude[ny = 440][nx = 640]; } x;'
        if url.endswith('.das'):
            return ('time { String units "seconds since 2016-01-01 00:00:00"; }\n'
                    'u_eastward { String units "m s-1"; }\nv_northward { String units "m s-1"; }')
        if 'Depth' in url:
            return ('Dataset { } x;\n' + '-' * 45 + '\n' + axis('Latitude', 417, 35.1, 440)
                    + axis('Longitude', 605, -121.18, 640) + 'Depth[1]\n0.0\n')
        return next(text for name, text in self.bodies.items() if name + '.ascii' in url)


def bodies_with(**changes):
    """First file malformed through changes {key: values}; the later file stays healthy."""
    data = arrays()
    data.update(changes)
    return {FILES[0]: body(data), FILES[1]: body(arrays(filename=FILES[1]))}


def as_source(client, previous=None):
    return source('wcofs', 'NOAA WCOFS surface currents', 'forecast', 'https://tidesandcurrents.noaa.gov/', 36,
                  lambda c: wcofs(c, REGION, NOW), NOW, previous, client_factory=lambda now: client)


class WcofsFrameShapeTests(unittest.TestCase):
    def test_equal_short_long_and_empty_spatial_arrays_refuse(self):
        self.assertEqual(len(wcofs(Client(), REGION, NOW)['frames']), 2)  # control: n entries everywhere
        for size in (N - 1, N + 1, 0):
            changes = {k: (arrays()[k] * 2)[:size] for k in SPATIAL}
            with self.subTest(size=size):
                self.assertEqual({len(v) for v in changes.values()}, {size})
                with self.assertRaisesRegex(ValueError, rf'^WCOFS Latitude has {size} values for {N} requested cells'):
                    wcofs(Client(bodies_with(**changes)), REGION, NOW)
                result = as_source(Client(bodies_with(**changes)))
                self.assertEqual((result['status'], result['data']), ('failed', None))
                self.assertTrue(result['issue'].startswith('ValueError: WCOFS Latitude'))

    def test_each_spatial_array_requires_requested_cardinality(self):
        for key in SPATIAL:
            for size in (N - 1, N + 1):
                with self.subTest(array=key, size=size):
                    values = (arrays()[key] * 2)[:size]
                    with self.assertRaisesRegex(ValueError, rf'^WCOFS {key} has {size} values for {N} requested cells'):
                        wcofs(Client(bodies_with(**{key: values})), REGION, NOW)

    def test_time_array_requires_one_value(self):
        for times in ([], [1.0, 2.0]):
            with self.subTest(times=times):
                with self.assertRaisesRegex(ValueError, rf'^WCOFS time has {len(times)} values, expected 1'):
                    wcofs(Client(bodies_with(time=times)), REGION, NOW)
        self.assertEqual(len(wcofs(Client(), REGION, NOW)['frames']), 2)

    def test_later_malformed_forecast_frame_fails_loader(self):
        for change in ({'mask': arrays()['mask'][:-1]}, {'time': []}):
            with self.subTest(change=sorted(change)):
                bodies = {FILES[0]: body(arrays(filename=FILES[0]))}
                later = arrays(filename=FILES[1])
                later.update(change)
                bodies[FILES[1]] = body(later)
                with self.assertRaisesRegex(ValueError, FILES[1]):
                    wcofs(Client(bodies), REGION, NOW)

    def test_complete_masked_grid_remains_missing(self):
        control = wcofs(Client(), REGION, NOW)
        self.assertEqual((control['valid_cells'], control['total_cells']), (WET, N))
        self.assertEqual(as_source(Client())['status'], 'ok')
        dry = {k: v for k, v in arrays(wet=0).items()}
        dry_bodies = {FILES[0]: body(dry), FILES[1]: body(arrays(wet=0, filename=FILES[1]))}
        out = wcofs(Client(dry_bodies), REGION, NOW)
        self.assertEqual((out['valid_cells'], out['total_cells']), (0, N))
        result = as_source(Client(dry_bodies), previous={'data': {'old': True}, 'last_success_at': 'then'})
        self.assertEqual((result['status'], result['issue']),
                         ('missing', 'No usable cells in this regional grid; no gap filling applied'))
        self.assertEqual(result['data']['total_cells'], N)  # new complete (dry) data, not the retained previous

    def test_shape_failure_retains_previous_data_and_clocks(self):
        bad = Client(bodies_with(**{k: arrays()[k][:-1] for k in SPATIAL}))
        previous = {'data': {'frames': ['prior']}, 'last_success_at': '2026-11-01T10:00:00Z',
                    'data_retrieved_at': '2026-11-01T09:59:00Z'}
        retained = as_source(bad, previous)
        self.assertEqual(retained['status'], 'retained')
        self.assertEqual(retained['data'], previous['data'])
        self.assertEqual((retained['last_success_at'], retained['data_retrieved_at']),
                         (previous['last_success_at'], previous['data_retrieved_at']))
        self.assertIn('WCOFS Latitude has 195 values', retained['issue'])
        failed = as_source(Client(bodies_with(**{k: arrays()[k][:-1] for k in SPATIAL})))
        self.assertEqual((failed['status'], failed['data']), ('failed', None))
        self.assertNotIn('last_success_at', failed)


if __name__ == '__main__':
    unittest.main()

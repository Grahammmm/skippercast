"""RF1020-2: ocean.wcofs() keeps the instant of a zoned DAS time origin; the cycle-conflict guard still fires.
Everything is synthetic and in memory: a one-cell grid, a fake client that refuses unknown requests, sockets blocked."""
from datetime import datetime, timezone
from unittest import mock
import socket, unittest
from skippercast.pipeline.ocean import wcofs

NAME = 'wcofs.t03z.20261101.regulargrid.f018.nc'
NOW = datetime(2026, 11, 1, 22, tzinfo=timezone.utc)
REGION = {'bounds': [-121.2, 35.0, -120.8, 35.2]}
VALID = int(datetime(2026, 11, 1, 21, tzinfo=timezone.utc).timestamp())  # cycle 03z + f018
UNIT_S = {'seconds': 1, 'hours': 3600, 'days': 86400}


class Client:
    def __init__(self, das_time, coordinate=0.0):
        self.das_time, self.coordinate, self.urls = das_time, coordinate, []

    def get(self, url):
        self.urls.append(url)
        if url.endswith('catalog.xml'):
            return f'<dataset name="{NAME}"/>'
        if url.endswith('.dds'):
            return 'Dataset { Float64 Latitude[ny = 1][nx = 1]; } x;'
        if url.endswith('.das'):
            return ('time { String units "' + self.das_time + '"; }\n'
                    'u_eastward { String units "m s-1"; }\nv_northward { String units "m s-1"; }')
        if 'Depth' in url:
            return 'Dataset { } x;\n' + '-' * 45 + '\nLatitude[1][1]\n[0], 35.1\nLongitude[1][1]\n[0], -121.0\nDepth[1]\n0.0\n'
        if 'mask' in url:
            return ('Dataset { } x;\n' + '-' * 45 + '\nLatitude[1][1]\n[0], 35.1\nLongitude[1][1]\n[0], -121.0\n'
                    'mask[1][1]\n[0], 1.0\nu_eastward[1][1][1][1]\n[0][0][0], 0.1\nv_northward[1][1][1][1]\n[0][0][0], 0.2\n'
                    f'time[1]\n{self.coordinate!r}\n')
        raise AssertionError('unexpected request: ' + url)


def run(origin, unit='seconds', delta=0, fh_epoch=VALID):
    """Build the coordinate that places `origin` at fh_epoch+delta and run the real reader."""
    zone = datetime.fromisoformat(origin.replace('Z', '+00:00').replace('UTC', '').strip())
    zone = zone if zone.tzinfo else zone.replace(tzinfo=timezone.utc)
    client = Client(f'{unit} since {origin}', (fh_epoch + delta - zone.timestamp()) / UNIT_S[unit])
    return wcofs(client, REGION, NOW), client


class WcofsTimeOriginTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.create_connection'):
            patcher = mock.patch(target, side_effect=AssertionError('provider access attempted'))
            patcher.start(); self.addCleanup(patcher.stop)

    def test_equivalent_zoned_origins_preserve_frame_instant(self):
        control = run('2016-01-01T00:00:00+00:00')[0]
        self.assertEqual(control['frames'][0]['time'], VALID)
        for origin in ('2016-01-01T01:00:00+01:00', '2015-12-31T16:00:00-08:00', '2016-01-01T05:30:00+05:30',
                       '2016-01-01T00:00:00+00:00:30', '2015-12-31T23:59:30+00:00', '2016-01-01T00:00:00-00:00:30'):
            with self.subTest(origin=origin):
                out, _ = run(origin)
                self.assertEqual(out['frames'], control['frames'])
                self.assertEqual((out['valid_from'], out['valid_through'], out['issued_at']),
                                 (VALID, VALID, control['issued_at']))
                self.assertEqual((out['total_cells'], out['valid_cells']), (control['total_cells'], control['valid_cells']))

    def test_origin_units_preserve_instant(self):
        origins = {'seconds': '2016-01-01T01:00:00+01:00', 'hours': '2026-11-01T17:00:00+05:30', 'days': '2026-11-01T01:00:00-08:00'}
        for unit, origin in origins.items():
            with self.subTest(unit=unit):
                out, client = run(origin, unit)
                self.assertGreater(client.coordinate, 0)
                self.assertEqual(out['frames'][0]['time'], VALID)
        self.assertEqual(run('2026-11-01T17:00:00+05:30', 'hours')[1].coordinate, 9.5)  # fractional hours
        self.assertEqual(run('2026-11-01T01:00:00-08:00', 'days')[1].coordinate, 0.5)  # fractional days

    def test_naive_z_and_utc_origins_remain_utc(self):
        control = run('2016-01-01T00:00:00+00:00')[0]
        for origin in ('2016-01-01T00:00:00', '2016-01-01T00:00:00Z', '2016-01-01 00:00:00 UTC', '2016-01-01 00:00:00'):
            with self.subTest(origin=origin):
                self.assertEqual(run(origin)[0]['frames'], control['frames'])

    def test_real_cycle_conflict_still_fails(self):
        for origin in ('2016-01-01T00:00:00+00:00', '2016-01-01T01:00:00+01:00', '2015-12-31T16:00:00-08:00'):
            for delta in (61, -61, 3601, -7200):
                with self.subTest(origin=origin, delta=delta), self.assertRaisesRegex(
                        ValueError, r'^WCOFS valid time conflicts with cycle$'):
                    run(origin, delta=delta)
            with self.subTest(origin=origin, edge=60):  # exactly 60 s keeps the existing tolerance
                self.assertEqual(run(origin, delta=60)[0]['frames'][0]['time'], VALID + 60)
                self.assertEqual(run(origin, delta=-60)[0]['frames'][0]['time'], VALID - 60)

    def test_bad_origin_is_not_repaired(self):
        for origin in ('2016-02-31T00:00:00', '2016-01-01Tnonsense', '2016-01-01T00:00:00+25:00', '2016-01-01T00:00:00+99:99'):
            client = Client('seconds since ' + origin)
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                wcofs(client, REGION, NOW)
            self.assertFalse(any('mask' in url for url in client.urls))  # failed before any forecast-hour read

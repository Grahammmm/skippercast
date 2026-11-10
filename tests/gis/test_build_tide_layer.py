"""MAPLAYER-TIDE-1: tide layer builder: sector selection, CO-OPS parsing, private output. No network."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import build_tide_layer as btl

SECTORS = {'sectors': [
    {'id': 'morro-conception', 'latitude': [34.45, 35.35]},
    {'id': 'cambria-morro', 'latitude': [35.35, 35.6]},
    {'id': 'del-norte', 'latitude': [41.7, 42.0]},
]}
LISTING = {'stations': [
    {'id': '9412110', 'name': 'PORT SAN LUIS', 'lat': 35.169, 'lng': -120.754, 'type': 'R'},
    {'id': '9412553', 'name': 'San Simeon', 'lat': 35.642, 'lng': -121.188, 'type': 'S'},     # north of the bands
    {'id': '9999999', 'name': 'Inland', 'lat': 35.2, 'lng': -118.0, 'type': 'R'},            # east of the lon range
    {'id': '9414290', 'name': 'San Francisco', 'lat': 37.806, 'lng': -122.465, 'type': 'R'},  # other sector
    {'id': '9410000', 'name': 'Band edge', 'lat': 35.35, 'lng': -120.9, 'type': 'S'},        # lands in cambria-morro
]}


def hilo(*rows):
    return {'predictions': [{'t': t, 'v': str(v), 'type': k} for t, v, k in rows]}


GOOD = hilo(('2026-11-07 03:00', 5.5, 'H'), ('2026-11-07 09:10', -0.1, 'L'), ('2026-11-07 15:30', 5.0, 'H'),
            ('2026-11-07 21:40', 0.8, 'L'))


def _refuse_constant(name):
    raise ValueError(name)


class SelectTests(unittest.TestCase):
    def test_sector_bands_and_longitude(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 's.json'
            f.write_text(json.dumps(SECTORS))
            bands = btl.sector_bounds(f, ['morro-conception', 'cambria-morro'])
            got = btl.select_stations(LISTING['stations'], bands)
            self.assertEqual([s['id'] for s in got], ['9410000', '9412110'])        # north to south
            self.assertEqual({s['id']: s['sector'] for s in got},
                             {'9412110': 'morro-conception', '9410000': 'cambria-morro'})
            self.assertEqual({s['id']: s['kind'] for s in got}, {'9412110': 'harmonic', '9410000': 'subordinate'})
            with self.assertRaises(SystemExit):
                btl.sector_bounds(f, ['nowhere'])


class ParseTests(unittest.TestCase):
    def test_extremes_utc_sorted(self):
        out = btl.parse_extremes(hilo(('2026-11-07 09:10', -0.1, 'L'), ('2026-11-07 03:00', 5.5, 'H')))
        self.assertEqual(out, [{'t': '2026-11-07T03:00Z', 'type': 'H', 'v': 5.5},
                               {'t': '2026-11-07T09:10Z', 'type': 'L', 'v': -0.1}])

    def test_provider_error_and_missing_row_fail(self):
        with self.assertRaises(ValueError):
            btl.parse_extremes({'error': {'message': 'No predictions'}})
        with self.assertRaises(ValueError):   # two highs in a row: a row is missing
            btl.parse_extremes(hilo(('2026-11-07 03:00', 5.5, 'H'), ('2026-11-07 15:00', 5.0, 'H')))


    def test_extremes_refuse_nonfinite_heights(self):
        for bad in ('NaN', 'Infinity', '-Infinity', '1e999', '-1e999', float('nan'), float('inf'), float('-inf')):
            for rows in ([('2026-11-07 03:00', bad, 'H')],
                         [('2026-11-07 03:00', 5.5, 'H'), ('2026-11-07 09:10', bad, 'L')]):
                with self.assertRaises(ValueError) as cm:
                    btl.parse_extremes(hilo(*rows))
                self.assertIn('non-finite tide height at 2026-11-07T', str(cm.exception))

    def test_finite_heights_preserve_rounding_and_bytes(self):
        out = btl.parse_extremes(hilo(('2026-11-07 03:00', '5.1234', 'H'), ('2026-11-07 09:10', 0, 'L'),
                                      ('2026-11-07 15:30', -0.0004, 'H'), ('2026-11-07 21:40', '-1.5', 'L')))
        self.assertEqual([r['v'] for r in out], [5.123, 0.0, -0.0, -1.5])
        text = json.dumps(out)
        self.assertEqual(text, '[{"t": "2026-11-07T03:00Z", "type": "H", "v": 5.123}, '
                               '{"t": "2026-11-07T09:10Z", "type": "L", "v": 0.0}, '
                               '{"t": "2026-11-07T15:30Z", "type": "H", "v": -0.0}, '
                               '{"t": "2026-11-07T21:40Z", "type": "L", "v": -1.5}]')


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sectors = Path(self.tmp.name) / 's.json'
        self.sectors.write_text(json.dumps(SECTORS))
        self.now = dt.datetime(2026, 11, 7, 16, 6, tzinfo=dt.timezone.utc)

    def test_build_records_time_and_failures_and_labels(self):
        def fetch(url):
            if url == btl.STATIONS_URL:
                return LISTING
            return GOOD if 'station=9412110' in url else {'error': {'message': 'none'}}
        doc = btl.build(self.sectors, ['morro-conception', 'cambria-morro'], 'test', self.now, 8, fetch=fetch, pause=0)
        self.assertEqual([s['id'] for s in doc['stations']], ['9412110'])
        self.assertEqual([f['id'] for f in doc['failed']], ['9410000'])
        self.assertEqual(doc['fetched_at'], '2026-11-07T16:06Z')
        self.assertEqual(doc['window'], {'begin': '2026-11-06', 'end': '2026-11-15', 'time_zone': 'UTC'})
        self.assertIn('NOT FOR NAVIGATION', doc['labels']['navigation'])
        self.assertIn('not current', doc['labels']['shows'])
        self.assertIn('PREDICTION', doc['labels']['kind'])

    def test_all_failed_writes_nothing(self):
        def fetch(url):
            return LISTING if url == btl.STATIONS_URL else {'error': {'message': 'none'}}
        with self.assertRaises(SystemExit):
            btl.build(self.sectors, ['morro-conception'], 'test', self.now, 8, fetch=fetch, pause=0)

    def test_build_excludes_nonfinite_station_but_keeps_valid_station(self):
        bad = hilo(('2026-11-07 03:00', 5.5, 'H'), ('2026-11-07 09:10', 'NaN', 'L'), ('2026-11-07 15:30', 5.0, 'H'),
                   ('2026-11-07 21:40', 0.8, 'L'))
        def fetch(url):
            if url == btl.STATIONS_URL:
                return LISTING
            return GOOD if 'station=9412110' in url else bad
        doc = btl.build(self.sectors, ['morro-conception', 'cambria-morro'], 'test', self.now, 8, fetch=fetch, pause=0)
        self.assertEqual([s['id'] for s in doc['stations']], ['9412110'])
        self.assertEqual([f['id'] for f in doc['failed']], ['9410000'])
        self.assertIn('non-finite tide height', doc['failed'][0]['reason'])
        text = json.dumps(doc)
        self.assertNotIn('NaN', text)
        json.loads(text, parse_constant=_refuse_constant)   # strict: no NaN/Infinity constants

    def test_all_nonfinite_stations_leave_existing_output_untouched(self):
        bad = hilo(('2026-11-07 03:00', '1e999', 'H'), ('2026-11-07 09:10', 0.1, 'L'), ('2026-11-07 15:30', 5.0, 'H'),
                   ('2026-11-07 21:40', 0.8, 'L'))
        def fetch(url):
            return LISTING if url == btl.STATIONS_URL else bad
        real_build = btl.build
        out = Path(self.tmp.name) / 'o' / 'x.json'
        out.parent.mkdir()
        for preseed in (True, False):
            out.unlink(missing_ok=True)
            if preseed:
                out.write_bytes(b'sentinel')
            with mock.patch.object(btl, 'build', lambda *a, **k: real_build(*a, fetch=fetch, pause=0, **k)):
                with self.assertRaises(SystemExit):
                    btl.main(['--sectors', 'morro-conception', '--output', str(out)])
            self.assertEqual(out.read_bytes() if preseed else out.exists(), b'sentinel' if preseed else False)
            self.assertFalse(out.with_suffix('.part').exists())

    def test_request_url_is_hilo_mllw_gmt(self):
        url = btl.predictions_url('9412110', dt.date(2026, 11, 6), dt.date(2026, 11, 15))
        for part in ('interval=hilo', 'datum=MLLW', 'time_zone=gmt', 'begin_date=20261106', 'end_date=20261115'):
            self.assertIn(part, url)

    def test_default_output_is_under_private_var_and_gitignored(self):
        out = btl.ROOT / 'var' / 'tide' / 'tide-layer-central-coast.json'
        self.assertEqual(out.relative_to(btl.ROOT).parts[0], 'var')
        self.assertIn('var/', (btl.ROOT / '.gitignore').read_text().split())
        target = Path(self.tmp.name) / 'a' / 'x.json'
        btl.write_private({'k': 1}, target)
        self.assertEqual(json.loads(target.read_text()), {'k': 1})
        self.assertFalse(target.with_suffix('.part').exists())

    def test_northern_sector_gets_wide_default_longitude(self):
        listing = {'stations': [{'id': '9419750', 'name': 'Crescent City', 'lat': 41.74561, 'lng': -124.18439, 'type': 'R'}]}
        self.assertEqual(btl.default_lon(['del-norte']), btl.CALIFORNIA_LON)
        self.assertEqual(btl.default_lon(btl.CENTRAL_COAST.split(',')), btl.DEFAULT_LON)
        def fetch(url):
            return listing if url == btl.STATIONS_URL else GOOD
        doc = btl.build(self.sectors, ['del-norte'], 'north', self.now, 8, fetch=fetch, pause=0)
        self.assertEqual([s['id'] for s in doc['stations']], ['9419750'])

    def test_name_must_be_publication_guard_shape(self):
        self.assertEqual(btl.layer_name('south-coast-2'), 'south-coast-2')
        for bad in ('Central_Coast', 'a/b', ''):
            with self.assertRaises(argparse.ArgumentTypeError):
                btl.layer_name(bad)


if __name__ == '__main__':
    unittest.main()
